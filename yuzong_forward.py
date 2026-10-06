#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
余总转发文案 —— 社媒运营翻车模拟器

你是一名大厂社媒运营。屏幕上是一条待转发的微博，
转发语里混入了内部备注（[余总转发文案][老板还没审]……）。
倒计时内输入编号删掉备注，再输入「发」发送。
删错正文 / 超时 / 带着备注手滑发出 —— 都会翻车。

纯属虚构，善意玩梗。
"""

from __future__ import annotations

import argparse
import random
import select
import sys
import time

# ------------------------------------------------------------------
# 素材（纯属虚构，致敬 2026-10-04 热梗，善意玩梗无恶意）
# ------------------------------------------------------------------

BODIES = [
    "【新品发布】今晚8点，年度旗舰发布会不见不散，直播间抽三台新机！",
    "【官宣】新系统流畅度提升40%，这次是真的遥遥领先了",
    "【福利】转发+关注，抽10位粉丝送限量版充电宝，截止本周五",
    "【预热】明早10点公布新品外观，猜中配色送耳机",
    "【直播预告】余总今晚空降直播间，聊聊新机的黑科技",
    "【开售战报】首销10分钟破万台，感谢大家，备货正在路上",
    "【科普】新机的卫星消息功能，没信号也能发短信",
    "【联名】这次和敦煌博物馆搞了个大事情，敬请期待",
]

# 必须删掉的内部备注（删干净才能发）
NOTES = [
    "余总转发文案",
    "老板还没审",
    "删括号内",
    "配图还没P",
    "记得@余总",
    "先别发，等通知",
    "把遥遥领先改成大幅领先",
    "法务说这句有风险",
    "数据还没核对完",
    "删我",
    "内部测试链接别点",
    "这句是余总原话，别改",
    "等老板娘点头再发",
    "热搜词条已买好",
]

# 长得像备注、但其实是正文的诱饵（手贱删了就翻车）
DECOYS = [
    "投票",
    "链接",
    "抽奖",
    "直播预约",
    "话题",
    "购买链接",
    "评论区见",
]

# ------------------------------------------------------------------
# 翻车结算
# ------------------------------------------------------------------

FLIPS = {
    "small":   ("小翻车·评论区玩梗", "1条备注泄露：#余总转发文案# 阅读破10万，网友：备注比正文好看"),
    "medium":  ("中翻车·登顶热搜",   "2条备注泄露：空降热搜第一，运营连夜删博重发"),
    "big":     ("大翻车·余总亲自下场", "3条备注泄露：余总幽默回应——文案是我让发的，备注也是，全网狂欢"),
    "decoy":   ("史诗翻车·删了正文", "你把正文里的东西删了！粉丝在评论区排队要链接"),
    "wrong":   ("删错翻车·删了个寂寞", "编号不对，你删掉了正文的一部分，发出去前言不搭后语"),
    "timeout": ("超时翻车·原样发出", "倒计时结束，备注一个没删，全发出去了，运营连夜删博"),
    "slip":    ("手滑翻车·三连击",   "无效指令太多，手机差点飞出去，备注原地起飞"),
}


def flip_by_leak(n: int) -> str:
    if n <= 1:
        return "small"
    if n == 2:
        return "medium"
    return "big"


# ------------------------------------------------------------------
# 草稿
# ------------------------------------------------------------------

class Draft:
    """一条待发微博：正文（备注以内联括号混入）+ 编号条目清单。"""

    def __init__(self, text: str, items: list[tuple[str, bool]]):
        self.text = text                      # 含 [备注] 内联的正文
        self.items = items                    # [(条目文本, 是否真备注)]
        self.deleted = [False] * len(items)

    @property
    def notes_left(self) -> int:
        return sum(1 for (_, is_note), d in zip(self.items, self.deleted)
                   if is_note and not d)

    def delete(self, idx: int) -> bool:
        """删第 idx（0-based）个条目。返回 True=删的是备注，False=误删正文。
        越界抛 IndexError，重复删抛 ValueError。"""
        if not 0 <= idx < len(self.items):
            raise IndexError(f"没有第 {idx + 1} 号条目")
        if self.deleted[idx]:
            raise ValueError(f"第 {idx + 1} 号条目已经删过了")
        self.deleted[idx] = True
        return self.items[idx][1]

    def render(self) -> str:
        lines = [self.text, "后台条目："]
        for i, ((text, _), d) in enumerate(zip(self.items, self.deleted)):
            mark = "（已删）" if d else ""
            lines.append(f"  [{i + 1}] {text}{mark}")
        return "\n".join(lines)


def build_draft(rng: random.Random, level: int) -> Draft:
    n_notes = min(2 + (level - 1), 5)          # 1级2条，每级+1，上限5
    n_decoys = 0 if level == 1 else (1 if level == 2 else 2)
    notes = rng.sample(NOTES, n_notes)
    decoys = rng.sample(DECOYS, n_decoys)
    items = [(t, True) for t in notes] + [(t, False) for t in decoys]
    rng.shuffle(items)
    text = rng.choice(BODIES)
    for t, _ in items:                        # 备注以内联括号混入正文
        pos = rng.randint(0, len(text))
        text = text[:pos] + f"[{t}]" + text[pos:]
    return Draft(text, items)


def time_limit(level: int) -> int:
    return max(26 - 2 * level, 10)


# ------------------------------------------------------------------
# 指令解析
# ------------------------------------------------------------------

def parse_command(line: str) -> tuple[list[int], bool, bool, int]:
    """解析一行输入 -> (编号列表, 是否发送, 是否退出, 无效token数)。"""
    digits: list[int] = []
    send = quit_ = False
    bad = 0
    for tok in line.split():
        if tok == "发":
            send = True
        elif tok == "q":
            quit_ = True
        elif tok.isdigit():
            digits.append(int(tok))
        else:
            bad += 1
    return digits, send, quit_, bad


def input_timeout(prompt: str, timeout: float) -> str | None:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if not r:
        return None
    return sys.stdin.readline().rstrip("\n")


# ------------------------------------------------------------------
# 回合
# ------------------------------------------------------------------

def play_interactive(rng: random.Random, level: int) -> dict:
    draft = build_draft(rng, level)
    limit = time_limit(level)
    mistakes = 0
    start = time.time()
    print(f"\n—— 第 {level} 轮 · 限时 {limit} 秒 ——")
    while True:
        remain = limit - (time.time() - start)
        if remain <= 0:
            return {"kind": "flip", "flip": "timeout"}
        print("-" * 40)
        print(draft.render())
        print("-" * 40)
        print('指令：输入编号删备注（如"1 3"），输入"发"发送，"q"退出')
        line = input_timeout(f"[剩{remain:.0f}s] > ", remain)
        if line is None:
            return {"kind": "flip", "flip": "timeout"}
        digits, send, quit_, bad = parse_command(line)
        if quit_:
            return {"kind": "quit"}
        mistakes += bad
        if bad:
            print(f"？无效指令（{bad}次），手滑警告 {mistakes}/3")
        if mistakes >= 3:
            return {"kind": "flip", "flip": "slip"}
        for d in digits:
            try:
                is_note = draft.delete(d - 1)
            except (IndexError, ValueError) as e:
                print(f"删错了：{e}")
                return {"kind": "flip", "flip": "wrong"}
            if not is_note:
                print(f"糟了：[{draft.items[d - 1][0]}] 是正文内容！")
                return {"kind": "flip", "flip": "decoy"}
            print(f"已删除备注 [{draft.items[d - 1][0]}]")
        if send:
            n = draft.notes_left
            if n == 0:
                score = int(remain * 10) + level * 50
                return {"kind": "success", "score": score}
            return {"kind": "flip", "flip": flip_by_leak(n)}


def auto_round(rng: random.Random, level: int, skill: float = 0.85) -> dict:
    """AI 运营：逐条判断备注/正文，删完发送。全程由 rng 驱动，可复现。"""
    draft = build_draft(rng, level)
    limit = time_limit(level)
    # 5% 概率手滑：看都不看直接发出
    if rng.random() < 0.05:
        return {"kind": "flip", "flip": flip_by_leak(draft.notes_left)}
    t = 0.0
    for i, (_, is_note) in enumerate(draft.items):
        p_correct = max(0.5, skill - 0.04 * level)
        ai_thinks_note = is_note if rng.random() < p_correct else (not is_note)
        t += rng.uniform(0.8, 1.6)
        if t >= limit:
            return {"kind": "flip", "flip": "timeout"}
        if ai_thinks_note:
            if not draft.delete(i):            # 误删正文
                return {"kind": "flip", "flip": "decoy"}
    n = draft.notes_left
    if n == 0:
        return {"kind": "success", "score": level * 50 + 100}
    return {"kind": "flip", "flip": flip_by_leak(n)}


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def show_result(res: dict) -> None:
    if res["kind"] == "success":
        print(f"\n稳！文案干净发出，得分 +{res['score']}，余总点了个赞")
    elif res["kind"] == "flip":
        title, desc = FLIPS[res["flip"]]
        print(f"\n翻车！【{title}】\n{desc}")


def cmd_auto(games: int, seed: int, skill: float) -> None:
    rng = random.Random(seed)
    flips = 0
    kinds: dict[str, int] = {}
    for g in range(1, games + 1):
        level = (g - 1) % 5 + 1
        res = auto_round(rng, level, skill)
        if res["kind"] == "flip":
            flips += 1
            key = FLIPS[res["flip"]][0]
            kinds[key] = kinds.get(key, 0) + 1
            print(f"第{g:2d}局（{level}级）：翻车【{FLIPS[res['flip']][0]}】")
        else:
            print(f"第{g:2d}局（{level}级）：成功 +{res['score']}")
    print("-" * 40)
    print(f"共 {games} 局：翻车 {flips} 局，翻车率 {flips / games:.0%}")
    for k, v in sorted(kinds.items(), key=lambda x: -x[1]):
        print(f"  {k}：{v} 次")


def cmd_play(seed: int | None) -> None:
    rng = random.Random(seed)
    total = 0
    level = 1
    while True:
        res = play_interactive(rng, level)
        if res["kind"] == "quit":
            print(f"\n运营下班，本次得分 {total}")
            return
        show_result(res)
        if res["kind"] == "flip":
            print(f"\n游戏结束！闯到第 {level} 轮，总分 {total}")
            return
        total += res["score"]
        level += 1


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="余总转发文案 —— 社媒运营翻车模拟器")
    ap.add_argument("--auto", action="store_true", help="AI 运营自动玩")
    ap.add_argument("--games", type=int, default=10, help="自动局数")
    ap.add_argument("--seed", type=int, default=None, help="随机种子")
    ap.add_argument("--skill", type=float, default=0.85, help="AI 运营靠谱程度 0~1")
    args = ap.parse_args(argv)

    if args.auto:
        cmd_auto(args.games, args.seed if args.seed is not None else 0, args.skill)
        return
    if not sys.stdin.isatty():
        print("交互模式需要终端运行；或使用 --auto 自动演示。")
        sys.exit(2)
    print("=" * 40)
    print("余总转发文案 —— 社媒运营翻车模拟器")
    print("删掉混入正文的内部备注，再输入「发」！")
    print("=" * 40)
    cmd_play(args.seed)


if __name__ == "__main__":
    main()
