#!/usr/bin/env python3
"""Показывает события блоков GENERATE в заданный момент времени GPSS-модели.

Пример:
    ./get-time-moment.py -t 60 'GENERATE 20' 'GENERATE 10,,20'
    ./get-time-moment.py --all -t 60 'GENERATE 20' 'GENERATE 10,,20'

Правила, которые учитываются:
    * A  - средний интервал между транзактами;
    * B  - разброс (в этой простой версии не моделируется);
    * C  - задержка/интервал первого транзакта;
    * D  - предельное число транзактов;
    * E  - приоритет.
    * Начальные транзакты (t=0) нумеруются в порядке блоков.
    * XN присваивается при планировании транзакта в FEC.
    * В один момент времени события идут по убыванию приоритета,
      при равенстве - по возрастанию номера блока.
"""

import argparse
import heapq
import sys
from fractions import Fraction

MAX_EVENTS = 10_000_000


def parse_number(text):
    text = text.strip()
    if not text:
        return None
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        pass
    try:
        return Fraction(float(text))
    except ValueError:
        raise ValueError(f"не удалось разобрать число: {text!r}") from None


def fmt(value):
    if value is None:
        return "—"
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return str(value.numerator)
        return f"{float(value):g}"
    return str(value)


def parse_generate(raw, index):
    line = raw.split(";", 1)[0].strip()
    if not line:
        raise ValueError(f"блок №{index}: пустая строка")

    tokens = line.split()
    gen_pos = next((i for i, tok in enumerate(tokens) if tok.upper() == "GENERATE"), None)
    if gen_pos is None:
        raise ValueError(f"блок №{index}: не найден GENERATE в {raw!r}")

    label = " ".join(tokens[:gen_pos]) or None
    rest = " ".join(tokens[gen_pos + 1:])
    operands = [part.strip() for part in rest.split(",")] if rest else []
    while len(operands) < 5:
        operands.append("")

    a_raw = operands[0]
    a = parse_number(a_raw)

    try:
        b = parse_number(operands[1])
    except ValueError:
        b = None
        print(
            f"Предупреждение: блок №{index}: операнд B задан не числом; "
            "разброс не моделируется.",
            file=sys.stderr,
        )

    c = parse_number(operands[2])
    d_raw = parse_number(operands[3])
    e = parse_number(operands[4])

    if a is None and d_raw is None:
        raise ValueError(f"блок №{index}: должен быть задан операнд A или D")
    if a is None:
        a = Fraction(0)

    if c == 0 and (a_raw.strip() or operands[1].strip()):
        c = None

    if b is not None and b != 0:
        print(
            f"Предупреждение: блок №{index}: операнд B (разброс) не моделируется; "
            f"интервал считается равным A={fmt(a)}.",
            file=sys.stderr,
        )

    if d_raw is not None and d_raw.denominator != 1:
        raise ValueError(f"блок №{index}: операнд D должен быть целым")
    if d_raw is not None and d_raw < 0:
        raise ValueError(f"блок №{index}: операнд D не может быть отрицательным")
    if e is not None and e.denominator != 1:
        raise ValueError(f"блок №{index}: операнд E (приоритет) должен быть целым")

    for name, value in (("A", a), ("B", b), ("C", c)):
        if value is not None and value < 0:
            raise ValueError(
                f"блок №{index}: операнд {name} не может быть отрицательным"
            )

    if a == 0 and d_raw is None:
        raise ValueError(
            f"блок №{index}: при A=0 нужен операнд D, иначе генерация бесконечна"
        )

    return {
        "index": index,
        "raw": raw,
        "label": label,
        "A": a,
        "B": b,
        "C": c,
        "D": None if d_raw is None else int(d_raw),
        "E": Fraction(0) if e is None else e,
    }


def event_line(event):
    label = f" [{event['label']}]" if event["label"] else ""
    return (
        f"Блок №{event['index']}{label} «{event['raw']}» — "
        f"генерируется транзакт XN{event['xn']} "
        f"(приоритет {fmt(event['priority'])})"
    )


def simulate(blocks, t, collect_all=False):
    heap = []
    events = []
    xn = 0
    processed = 0

    for block in blocks:
        limit = block["D"]
        if limit is not None and limit <= 0:
            block["scheduled"] = 0
            continue

        first_time = block["C"] if block["C"] is not None else block["A"]
        xn += 1
        block["scheduled"] = 1
        heapq.heappush(heap, (first_time, -block["E"], block["index"], xn, block))

    while heap:
        time, _neg_priority, _index, xn_of_tx, block = heap[0]
        if time > t:
            break

        heapq.heappop(heap)
        processed += 1
        if processed > MAX_EVENTS:
            raise RuntimeError("слишком много событий (возможно, интервал A равен 0)")

        if collect_all or time == t:
            events.append(
                {
                    "time": time,
                    "index": block["index"],
                    "raw": block["raw"],
                    "label": block["label"],
                    "priority": block["E"],
                    "xn": xn_of_tx,
                }
            )

        if block["D"] is None or block["scheduled"] < block["D"]:
            next_time = time + block["A"]
            block["scheduled"] += 1
            xn += 1
            heapq.heappush(
                heap, (next_time, -block["E"], block["index"], xn, block)
            )

    return events


def main():
    parser = argparse.ArgumentParser(
        description="Показать события блоков GENERATE в заданный момент времени GPSS-модели."
    )
    parser.add_argument(
        "-t", "--time", required=True, help="момент времени, например 60"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="вывести все события FEC от t=0 до указанного момента включительно",
    )
    parser.add_argument(
        "blocks", nargs="+", metavar="GENERATE", help="строки блоков GENERATE"
    )
    args = parser.parse_args()

    try:
        t = parse_number(args.time)
    except ValueError as exc:
        parser.error(str(exc))
    if t is None:
        parser.error("не задан момент времени")
    if t < 0:
        parser.error("момент времени не может быть отрицательным")

    try:
        blocks = [parse_generate(raw, i) for i, raw in enumerate(args.blocks, 1)]
        events = simulate(blocks, t, args.show_all)
    except (ValueError, RuntimeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"\033[31;mМомент времени t = {fmt(t)}\033[0;m")
    print()

    if args.show_all:
        if not events:
            print(f"Событий генерации до t = {fmt(t)} не было.")
            return 0

        print(f"События FEC до t = {fmt(t)} включительно (в порядке обработки):")
        print()
        current_time = None
        for number, event in enumerate(events, 1):
            if event["time"] != current_time:
                current_time = event["time"]
                if number != 1:
                    print()
                print(f"t = {fmt(current_time)}")
            print(f"  {number}. {event_line(event)}")

        print()
        print(f"Всего событий: {len(events)}")
        all_xn = sorted(event["xn"] for event in events)
        print(
            f"Все XN до t = {fmt(t)}: "
            + ", ".join(f"XN{xn}" for xn in all_xn)
        )
    else:
        if not events:
            print("Событий генерации в этот момент нет.")
            return 0

        print("События в этот момент (в порядке обработки FEC):")
        for number, event in enumerate(events, 1):
            print(f"{number}. {event_line(event)}")

        print()
        print(f"Всего событий: {len(events)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
