"""Deterministic current snapshot and separate history for private-board meetings."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

REQUIRED = {"round", "budget", "status", "goal", "summary", "decisions", "actions",
            "open_items", "parked", "event", "backend_notes"}
OPTIONAL = {"budget_approval"}
STATUSES = {"in_progress": "讨论中", "closed": "讨论已收束",
            "conditional": "条件收束，仍有未决", "paused": "已暂停"}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def validate(data):
    if not isinstance(data, dict) or not REQUIRED <= data.keys() or data.keys() - REQUIRED - OPTIONAL:
        raise ValueError("当前快照须完整提供规定字段；不要拼接旧正文或额外状态区")
    if type(data["round"]) is not int or type(data["budget"]) is not int or not 0 <= data["round"] <= data["budget"] or data["budget"] < 1:
        raise ValueError("轮数/预算须有效，已用不可超过约定预算")
    if data["status"] not in STATUSES:
        raise ValueError("未知讨论状态")
    for key in ("goal", "summary", "event", "backend_notes"):
        if not isinstance(data[key], str):
            raise ValueError("文字字段须为字符串")
    for key in ("decisions", "open_items", "parked"):
        if not isinstance(data[key], list) or any(not isinstance(x, str) for x in data[key]):
            raise ValueError("列表字段须为文字列表")
    if not isinstance(data["actions"], list):
        raise ValueError("actions须为列表")
    for action in data["actions"]:
        if not isinstance(action, dict) or set(action) != {"owner", "step", "when", "stop"} or any(not isinstance(v, str) or not v.strip() for v in action.values()):
            raise ValueError("行动须含责任/步骤产物/窗口/停损；未确认应如实写未确认")
    if "budget_approval" in data and (not isinstance(data["budget_approval"], str) or not data["budget_approval"].strip()):
        raise ValueError("预算变更依据须为真实许可文字")

def bullets(items):
    return "\n".join("- " + x for x in items) if items else "无。"

def render_front(data, events):
    actions = []
    for i, a in enumerate(data["actions"], 1):
        actions.append(f"{i}. **{a['step']}**\n   - 责任与权限：{a['owner']}\n   - 完成窗口：{a['when']}\n   - 验收、停损触发与处置：{a['stop']}")
    text = f"""# 私董会会议纪要与执行方案

## 当前状态
{STATUSES[data['status']]}；已用 {data['round']} / {data['budget']} 次实质答复。
本场目标：{data['goal']}
当前判断与收束依据：{data['summary']}

## 当前决议
{bullets(data['decisions'])}

## 当前执行方案
{chr(10).join(actions) if actions else '尚无已确认行动；不据此启动。'}

## 当前未决与取证
{bullets(data['open_items'])}

## 暂缓与下一场
{bullets(data['parked'])}

## 历史会议纪要（仅记录当时发生，不代表当前状态）
"""
    for event in events:
        text += f"\n### 第{event['sequence']}次记录 · 当时已用{event['round']}/{event['budget']}答\n{event['event']}\n"
    text += "\n文件是会议记录，不代表行动已执行；下一场须明确启动。\n"
    if re.search(r"\b(?:INV|BIZ|BP)-\d+\b|fingerprint|会话ID|消息ID", text, re.I):
        raise ValueError("阅读版含后台标识；移入backend_notes后重试")
    return text

def save(data, meeting, backend):
    validate(data)
    m = Path(meeting).resolve()
    m.parent.mkdir(parents=True, exist_ok=True)
    lock = m.with_name("." + m.stem + ".write-lock")
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError("本记录已有写入锁；不并发覆盖，确认已有写入完成后再重试")
    try:
        return _save_locked(data, meeting, backend)
    finally:
        lock.rmdir()

def _save_locked(data, meeting, backend):
    validate(data)
    m, b = Path(meeting).resolve(), Path(backend).resolve()
    if m == b or m.parent != b.parent:
        raise ValueError("阅读版和后台须为同一已授权目录中的不同文件")
    m.parent.mkdir(parents=True, exist_ok=True)
    ledger_path = m.with_name("." + m.stem + ".record.json")
    if ledger_path == b:
        raise ValueError("后台路径不可占用内部状态文件")
    targets = [m, b, ledger_path]
    originals = {path: path.read_bytes() if path.exists() else None for path in targets}
    ledger = None
    if originals[ledger_path] is not None:
        ledger = json.loads(originals[ledger_path])
        if ledger["paths"] != [str(m), str(b)]:
            raise ValueError("记录路径不一致")
        for path, expected in zip((m, b), ledger["hashes"]):
            if originals[path] is None or digest(originals[path]) != expected:
                raise ValueError("检测到外部修改或文件缺失，请先合并；未覆盖")
        previous = ledger["current"]
        if data["round"] < previous["round"]:
            raise ValueError("已用轮数不可归零或倒退")
        if data["budget"] != previous["budget"] and not data.get("budget_approval"):
            raise ValueError("预算变更缺少案主明确许可记录")
    elif originals[m] is not None or originals[b] is not None:
        raise ValueError("已有非本工具管理的文件，先保存备份并人工合并到新记录，不自动覆盖")
    history = (ledger["history"] + [ledger["current"]]) if ledger else []
    events = []
    for i, state in enumerate(history + [data], 1):
        events.append(dict(sequence=i, round=state["round"], budget=state["budget"], event=state["event"]))
    front = render_front(data, events)
    current_meta = {k: data[k] for k in ("round", "budget", "status", "goal", "summary")}
    back = "# 私董会后台记录\n\n## 唯一当前状态\n\n" + json.dumps(current_meta, ensure_ascii=False, indent=2)
    back += "\n\n## 本轮后台依据\n\n" + data["backend_notes"]
    if data.get("budget_approval"):
        back += "\n预算许可：" + data["budget_approval"]
    back += "\n\n## 历史事件（已被当前快照替代）\n"
    for i, state in enumerate(history, 1):
        back += f"\n### 历史记录{i} · 当时{state['round']}/{state['budget']}答\n{state['event']}\n{state['backend_notes']}\n"
    front_bytes, back_bytes = front.encode(), back.encode()
    new_ledger = dict(schema=1, paths=[str(m), str(b)], current=data, history=history,
                      hashes=[digest(front_bytes), digest(back_bytes)])
    targets = [m, b, ledger_path]
    outputs = [front_bytes, back_bytes, (json.dumps(new_ledger, ensure_ascii=False, indent=2)+"\n").encode()]
    if ledger:
        backup_root = m.parent / ("." + m.stem + "-history")
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix=f"{len(history):04d}-", dir=backup_root))
        for path in targets:
            (backup / path.name).write_bytes(originals[path])
    # All validation/rendering precedes mutation. Stage writes, retain recoverable originals.
    replaced = []
    with tempfile.TemporaryDirectory(prefix=".private-board-", dir=m.parent) as tmp:
        staged = []
        for i, payload in enumerate(outputs):
            path = Path(tmp) / str(i)
            path.write_bytes(payload)
            staged.append(path)
        # Cooperative writers share the lock; recheck visible external edits immediately before commit.
        for path in targets:
            current = path.read_bytes() if path.exists() else None
            if current != originals[path]:
                raise ValueError("保存准备期间发生外部修改；保留修改，未覆盖，请先合并")
        try:
            for path, staged_path in zip(targets, staged):
                os.replace(staged_path, path)
                replaced.append(path)
            for path, expected in zip(targets, outputs):
                if path.read_bytes() != expected:
                    raise OSError("保存后回读内容不符")
        except Exception:
            for path in reversed(replaced):
                written = outputs[targets.index(path)]
                if not path.exists() or path.read_bytes() != written:
                    raise OSError("回滚时发现新的外部修改，保留现场及历史备份，需合并")
                old = originals[path]
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(old)
            raise
    return {"ok": True, "round": data["round"], "budget": data["budget"],
            "meeting": str(m), "backend": str(b), "readback_verified": True,
            "meeting_sha256": digest(front_bytes), "backend_sha256": digest(back_bytes)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="完整当前快照JSON，不是部分patch")
    parser.add_argument("--meeting", required=True)
    parser.add_argument("--backend", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(save(json.loads(Path(args.input).read_text()), args.meeting, args.backend), ensure_ascii=False))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"未确认保存成功：{error}\n")

if __name__ == "__main__":
    main()
