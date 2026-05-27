"""
Wermes Client — 实时流式工具调用 + 非阻塞会话切换 + 会话续接
使用 hermes chat -q --resume 在已有会话中追加消息，避免每次创建新会话。
"""

import subprocess, json, re, os, time, sqlite3
from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import asyncio

app = FastAPI(title="Wermes Client")
HERMES_BIN = "hermes"
HERMES_HOME = os.environ.get("HERMES_HOME", "/mnt/d/hermus")
SKILLS_DIR = Path(HERMES_HOME) / "skills"
STATE_DB = Path(HERMES_HOME) / "state.db"
MEMORY_QUERY_PROMPT = "用中文列出你所有的记忆条目（memory和user profile），每条一行简短摘要。直接列，不要额外说明。"

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    baseline_id: Optional[int] = None  # 用于批准危险命令后清理第一次的失败消息

class ChatResponse(BaseModel):
    response: str; session_id: str; session_title: str

def run_hermes(cmd: list[str], timeout: int = 120) -> str:
    try:
        r = subprocess.run([HERMES_BIN] + cmd, capture_output=True, text=True, timeout=timeout, cwd=str(Path.home()))
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[超时]"

def parse_session_list(output: str) -> list[dict]:
    sessions = []
    for line in output.strip().split("\n"):
        if any(c in line for c in "─┌└┏┡"): continue
        if ("Preview" in line and "Last Active" in line) or ("Title" in line and "Preview" in line): continue
        if not line.strip(): continue
        m = re.match(r"^(.+?)\s{2,}(.+?)\s{2,}(\S+(?:\s+\S+)*?)\s+(\S+)$", line.strip())
        if m:
            sid, title, preview = m.group(4), m.group(1).strip(), m.group(2).strip()[:100]
            if sid in ("ID", "Src"): continue
            if title in ("—", ""): title = preview.split("。")[0].split("，")[0].split("\n")[0][:40]
            sessions.append({"id": sid, "title": title, "preview": preview, "last_active": m.group(3).strip()})
    return sessions

@app.get("/api/sessions")
async def list_sessions(limit: int = 50):
    return {"sessions": parse_session_list(run_hermes(["sessions", "list", "--limit", str(limit)]))}

@app.get("/api/sessions/{session_id}")
async def get_session_messages(session_id: str):
    output = run_hermes(["sessions", "export", "--session-id", session_id, "-"], timeout=10)
    messages = []
    for line in output.strip().split("\n"):
        if not line.strip(): continue
        try:
            msg = json.loads(line)
            if "messages" in msg and isinstance(msg["messages"], list):
                for m in msg["messages"]:
                    role = m.get("role", "")
                    if role in ("user", "assistant", "tool"):
                        content = m.get("content", "")
                        if content and len(content.strip()) > 0:
                            messages.append({"role": role, "content": content.strip(),
                                "tool_name": m.get("tool_name", ""), "timestamp": m.get("timestamp", 0)})
                break
        except: continue
    return {"session_id": session_id, "messages": messages[-100:]}

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    output = run_hermes(["sessions", "delete", session_id], timeout=10)
    return {"ok": "deleted" in output.lower() or "error" not in output.lower(), "message": output.strip()}

@app.get("/api/sessions/{session_id}/info")
async def get_session_info(session_id: str):
    output = run_hermes(["sessions", "export", "--session-id", session_id, "-"], timeout=10)
    info = {}
    for line in output.strip().split("\n"):
        if not line.strip(): continue
        try:
            msg = json.loads(line)
            if "messages" in msg:
                info = {"id": msg.get("id",session_id), "title": msg.get("title","—"),
                    "model": msg.get("model","?"), "started_at": msg.get("started_at",""),
                    "message_count": msg.get("message_count",0), "tool_call_count": msg.get("tool_call_count",0),
                    "input_tokens": msg.get("input_tokens",0), "output_tokens": msg.get("output_tokens",0),
                    "estimated_cost_usd": msg.get("estimated_cost_usd",0), "source": msg.get("source","cli")}
                break
        except: continue
    return {"session_id": session_id, "info": info}

TOOL_ICONS = {
    "terminal": "💻", "read_file": "📖", "write_file": "✏", "search_files": "🔍",
    "patch": "🔧", "memory": "🧠", "skill_view": "📋", "skill_manage": "📋",
    "vision_analyze": "👁", "delegate_task": "🤖", "web_search": "🌐",
    "execute_code": "🐍", "todo": "✅", "clarify": "❓",
}

async def _poll_tools(sid: str, seen_msgs: int):
    """获取新工具消息，实时查询命令详情（不再等进程结束）"""
    tools = []
    try:
        def _query():
            conn = sqlite3.connect(str(STATE_DB))
            c = conn.cursor()
            c.execute("""SELECT id, role, content, tool_name, timestamp 
                         FROM messages WHERE session_id=? AND role='tool' 
                         ORDER BY id LIMIT -1 OFFSET ?""", (sid, seen_msgs))
            rows = c.fetchall()
            new_seen = seen_msgs + len(rows)
            result = []
            for row in rows:
                msg_id, role, content, tn, ts = row[0], row[1], row[2], row[3], row[4]
                tn = tn or ""
                icon = TOOL_ICONS.get(tn, "⚙")
                command = f"{icon} {tn}"
                # 实时查：找到触发此 tool 的 assistant 消息中的 tool_calls
                c.execute("""SELECT tool_calls FROM messages 
                             WHERE session_id=? AND role='assistant' 
                             AND tool_calls IS NOT NULL AND id < ?
                             ORDER BY id DESC LIMIT 1""", (sid, msg_id))
                ar = c.fetchone()
                if ar and ar[0]:
                    try:
                        for tc in json.loads(ar[0]):
                            fn = tc.get("function", {})
                            if fn.get("name") == tn:
                                try: args = json.loads(fn.get("arguments", "{}"))
                                except: args = {}
                                command = _fmt_cmd(tn, args)
                                break
                    except: pass
                result.append((msg_id, role, content, tn, ts, command))
            conn.close()
            return result, new_seen
        rows, new_seen = await asyncio.to_thread(_query)
        for msg_id, role, content, tn, ts, command in rows:
            tools.append({
                "msg_id": msg_id, "role": role, "content": content or "",
                "tool_name": tn, "timestamp": ts or 0,
                "command": command,
            })
        seen_msgs = new_seen
    except: pass
    return {"tools": tools, "seen": seen_msgs}

async def _enrich_commands(sid: str):
    cmds = []
    try:
        def _query():
            conn = sqlite3.connect(str(STATE_DB))
            c = conn.cursor()
            c.execute("""SELECT t.id, a.tool_calls FROM messages t
                JOIN messages a ON a.session_id = t.session_id 
                    AND a.role = 'assistant' AND a.tool_calls IS NOT NULL
                    AND a.id = (SELECT MAX(id) FROM messages 
                                WHERE session_id=t.session_id AND role='assistant' 
                                AND tool_calls IS NOT NULL AND id < t.id)
                WHERE t.session_id = ? AND t.role = 'tool' ORDER BY t.id""", (sid,))
            rows = c.fetchall()
            conn.close()
            return rows
        rows = await asyncio.to_thread(_query)
        for tool_id, tc_json in rows:
            if not tc_json: continue
            try:
                for tc in json.loads(tc_json):
                    fn = tc.get("function", {})
                    try: args = json.loads(fn.get("arguments", "{}"))
                    except: args = {}
                    cmds.append({"msg_id": tool_id, "command": _fmt_cmd(fn.get("name", "?"), args)})
            except: pass
    except: pass
    return cmds

def _fmt_cmd(name: str, args: dict) -> str:
    if name == "terminal": return f"💻 terminal → {args.get('command', '')[:80]}"
    elif name == "read_file": return f"📖 read_file {args.get('path', '?')}"
    elif name == "write_file": return f"✏ write_file {args.get('path', '?')}"
    elif name == "search_files": return f"🔍 search_files \"{args.get('pattern', '?')[:50]}\""
    elif name == "patch": return f"🔧 patch {args.get('path', '?')}"
    elif name == "memory": return f"🧠 memory {args.get('action', '?')}"
    elif name == "skill_view": return f"📋 skill_view {args.get('name', '?')}"
    elif name == "vision_analyze": return f"👁 vision_analyze"
    elif name == "delegate_task": return f"🤖 delegate_task → {args.get('goal', '')[:60]}"
    else: return f"⚙ {name}"

@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    async def generate():
        # 记录第一阶段的基准消息 ID（用于批准后清理）
        baseline_id = 0
        if req.session_id:
            try:
                def _get_max():
                    conn = sqlite3.connect(str(STATE_DB))
                    c = conn.cursor()
                    c.execute("SELECT COALESCE(MAX(id),0) FROM messages WHERE session_id=?", (req.session_id,))
                    v = c.fetchone()[0]
                    conn.close()
                    return v
                baseline_id = await asyncio.to_thread(_get_max)
            except: pass

        if req.session_id:
            # 续接已有会话
            proc = subprocess.Popen(
                [HERMES_BIN, "chat", "-q", req.message, "--resume", req.session_id, "--quiet"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                cwd=str(Path.home()))
            sid = req.session_id
            yield f"data: {json.dumps({'type':'session','id':sid})}\n\n"
        else:
            # 新建会话
            proc = subprocess.Popen(
                [HERMES_BIN, "-z", req.message],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                cwd=str(Path.home()))
            await asyncio.sleep(1)
            sid = None
            for _ in range(5):
                latest = run_hermes(["sessions", "list", "--limit", "1"], timeout=5)
                parsed = parse_session_list(latest)
                if parsed: sid = parsed[0]["id"]; break
                await asyncio.sleep(0.5)
            yield f"data: {json.dumps({'type':'session','id':sid})}\n\n"

        # 轮询工具调用（首次立即查，然后循环）
        if sid:
            seen_msgs = 0
            # 首次立即轮询
            result = await _poll_tools(sid, seen_msgs)
            for t in result["tools"]:
                yield f"data: {json.dumps(t)}\n\n"
            seen_msgs = result["seen"]
            # 循环轮询
            while proc.poll() is None:
                await asyncio.sleep(0.3)
                result = await _poll_tools(sid, seen_msgs)
                for t in result["tools"]:
                    yield f"data: {json.dumps(t)}\n\n"
                seen_msgs = result["seen"]

        final_output = proc.stdout.read() if proc.stdout else ""
        proc.wait()
        clean = final_output
        if req.session_id:
            lines = final_output.strip().split("\n")
            filtered = [l for l in lines if not l.startswith("↻ Resumed") and not l.startswith("session_id:")]
            clean = "\n".join(filtered).strip()

        # 检测危险命令拒绝
        danger_info = _extract_danger(final_output)
        if danger_info:
            yield f"data: {json.dumps({'type':'danger','command':danger_info['command'],'description':danger_info['description'],'message':req.message,'session_id':sid,'baseline_id':baseline_id})}\n\n"
            yield f"data: {json.dumps({'type':'done'})}\n\n"
            return

        if req.session_id:
            yield f"data: {json.dumps({'type':'response','content':clean,'session_id':req.session_id,'session_title':'会话'})}\n\n"
        else:
            latest = run_hermes(["sessions", "list", "--limit", "1"], timeout=5)
            parsed = parse_session_list(latest)
            if parsed: sid, title = parsed[0]["id"], parsed[0]["title"]
            else: title = "新对话"
            yield f"data: {json.dumps({'type':'response','content':clean,'session_id':sid,'session_title':title})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


def _extract_danger(output: str) -> dict | None:
    """从 hermes 输出中提取被拒绝的危险命令信息"""
    if "DANGEROUS COMMAND" not in output or "✗ Denied" not in output:
        return None
    lines = output.split("\n")
    in_danger = False
    cmd_lines = []
    description = ""
    for line in lines:
        clean_line = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
        if "DANGEROUS COMMAND:" in clean_line:
            in_danger = True
            description = clean_line.split("DANGEROUS COMMAND:", 1)[-1].strip()
            continue
        if in_danger:
            if "Choice [" in clean_line or "✗ Denied" in clean_line:
                break
            if clean_line and not clean_line.startswith("["):
                cmd_lines.append(clean_line)
    if cmd_lines:
        return {"command": "\n".join(cmd_lines), "description": description}
    return None


@app.post("/api/chat/retry")
async def chat_retry(req: ChatRequest):
    """用 --yolo 重跑被拒绝的危险命令，先清理第一次的失败消息"""
    async def generate():
        sid = req.session_id
        # 清理第一次尝试的失败消息（保留原始用户消息）
        if req.baseline_id and sid:
            try:
                def _cleanup():
                    conn = sqlite3.connect(str(STATE_DB))
                    c = conn.cursor()
                    # 找到第一次尝试的用户消息 ID
                    c.execute("SELECT COALESCE(MIN(id),0) FROM messages WHERE session_id=? AND role='user' AND id > ?",
                              (sid, req.baseline_id))
                    user_msg_id = c.fetchone()[0]
                    # 删除第一次尝试中除用户消息外的所有消息
                    if user_msg_id:
                        c.execute("DELETE FROM messages WHERE session_id=? AND id > ? AND id != ?",
                                  (sid, req.baseline_id, user_msg_id))
                    else:
                        c.execute("DELETE FROM messages WHERE session_id=? AND id > ?",
                                  (sid, req.baseline_id))
                    conn.commit()
                    conn.close()
                await asyncio.to_thread(_cleanup)
            except: pass

        proc = subprocess.Popen(
            [HERMES_BIN, "chat", "-q", req.message, "--resume", sid, "--quiet", "--yolo"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            cwd=str(Path.home()))
        
        # 记录 retry 开始前的 max ID（用于之后删除 retry 创建的重复用户消息）
        retry_baseline = 0
        try:
            def _get_max2():
                conn = sqlite3.connect(str(STATE_DB))
                c = conn.cursor()
                c.execute("SELECT COALESCE(MAX(id),0) FROM messages WHERE session_id=?", (sid,))
                v = c.fetchone()[0]
                conn.close()
                return v
            retry_baseline = await asyncio.to_thread(_get_max2)
        except: pass
        
        yield f"data: {json.dumps({'type':'session','id':sid})}\n\n"

        if sid:
            seen_msgs = 0
            # 首次立即轮询
            result = await _poll_tools(sid, seen_msgs)
            for t in result["tools"]:
                yield f"data: {json.dumps(t)}\n\n"
            seen_msgs = result["seen"]
            while proc.poll() is None:
                await asyncio.sleep(0.3)
                result = await _poll_tools(sid, seen_msgs)
                for t in result["tools"]:
                    yield f"data: {json.dumps(t)}\n\n"
                seen_msgs = result["seen"]

        final_output = proc.stdout.read() if proc.stdout else ""
        proc.wait()
        
        # 删除 retry 创建的重复用户消息（保留第一次的原始用户消息）
        if retry_baseline and sid:
            try:
                def _cleanup_retry():
                    conn = sqlite3.connect(str(STATE_DB))
                    c = conn.cursor()
                    c.execute("DELETE FROM messages WHERE session_id=? AND role='user' AND id > ?",
                              (sid, retry_baseline))
                    conn.commit()
                    conn.close()
                await asyncio.to_thread(_cleanup_retry)
            except: pass
        
        clean = final_output
        lines = final_output.strip().split("\n")
        filtered = [l for l in lines if not l.startswith("↻ Resumed") and not l.startswith("session_id:")]
        clean = "\n".join(filtered).strip()

        yield f"data: {json.dumps({'type':'response','content':clean,'session_id':sid,'session_title':'会话'})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

@app.get("/api/skills")
async def list_skills():
    output = run_hermes(["skills", "list"], timeout=10)
    skills = []
    for line in output.strip().split("\n"):
        if any(c in line for c in "┏┡└") or "Name" in line: continue
        parts = [p.strip() for p in line.split("│")]
        if len(parts) >= 5:
            skills.append({"name":parts[1],"category":parts[2],"description":"","source":parts[3],"status":parts[4]})
    return {"skills": skills}

@app.get("/api/skills/{name}")
async def view_skill(name: str):
    sp = SKILLS_DIR / name / "SKILL.md"
    if sp.exists(): return {"name": name, "content": sp.read_text(encoding="utf-8")}
    output = run_hermes(["skills", "inspect", name], timeout=10)
    if "No exact match" in output:
        m = re.search(r"Did you mean one of these\?\n(.+)", output)
        if m:
            for sl in m.group(1).strip().split("\n"):
                sug = sl.strip().split("—")[0].strip()
                if sug:
                    o2 = run_hermes(["skills", "inspect", sug], timeout=10)
                    if "No exact match" not in o2: return {"name": name, "content": o2}
    return {"name": name, "content": output}

@app.get("/api/memory")
async def view_memory():
    return {"memory": run_hermes(["-z", MEMORY_QUERY_PROMPT], timeout=60).strip(), "user": ""}

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
async def index():
    return FileResponse(str(static_dir / "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7861, log_level="warning")
