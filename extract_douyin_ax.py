import argparse
import json
import re
from pathlib import Path

LINK_RE = re.compile(r"AXLink \((.*)\) .*URL: (https://www\.douyin\.com/(?:video|note)/(\d+))")
IMAGE_RE = re.compile(r"AXImage .* URL: (https://[^\s]+)")
STATIC_RE = re.compile(r"AXStaticText = \"(.*)\"")
LIST_RE = re.compile(r"^(\s*)- \[\d+\] AXList")
LINK_START_RE = re.compile(r"^\s*- \[\d+\] AXLink")


def parse_lines(lines):
    candidates = []
    for index, line in enumerate(lines):
        match = LINK_RE.search(line)
        if not match:
            continue
        url, native_id = match.group(2), match.group(3)
        link_text = match.group(1)
        cover = ""
        texts = []
        for following in lines[index + 1:index + 10]:
            if LINK_START_RE.match(following):
                break
            if not cover:
                image = IMAGE_RE.search(following)
                if image:
                    cover = image.group(1)
            static = STATIC_RE.search(following)
            if static:
                value = static.group(1)
                if not re.fullmatch(r"[\d.]+万?|\d+", value):
                    texts.append(value)
        visible_title = texts[-1] if texts else ""
        author = ""
        title = visible_title
        if "：" in link_text:
            author, remainder = link_text.split("：", 1)
            if visible_title and remainder.endswith(visible_title):
                remainder = remainder[:-len(visible_title)]
            remainder = re.sub(r"\s+(?:\d+(?:\.\d+)?万|\d+)\s*$", "", remainder).strip()
            title = remainder or visible_title
        if cover:
            candidates.append({"native_id": native_id, "title": title, "author": author,
                               "url": url, "cover": cover, "raw": {"link_text": link_text, "visible_title": visible_title}})
    return candidates


def extract_file(path):
    lines = Path(path).read_text(errors="replace").split("<mcp-result-extras>")[0].splitlines()
    lists = []
    for index, line in enumerate(lines):
        match = LIST_RE.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        end = len(lines)
        for cursor in range(index + 1, len(lines)):
            following = lines[cursor]
            if re.match(r"^\s*- \[\d+\]", following) and len(following) - len(following.lstrip()) <= indent:
                end = cursor
                break
        items = parse_lines(lines[index + 1:end])
        if items:
            lists.append(items)
    if not lists:
        return parse_lines(lines)
    return max(lists, key=len)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--collection", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected", type=int)
    args = parser.parse_args()
    items = {}
    for input_path in args.inputs:
        for item in extract_file(input_path):
            items.setdefault(item["native_id"], item)
    result = [{"platform": "douyin", "collection": args.collection, "title": item["title"],
               "author": item["author"], "url": item["url"], "cover": item["cover"], "raw": item["raw"]}
              for item in items.values()]
    if args.expected is not None and len(result) != args.expected:
        raise ValueError(f"{args.collection} 应读取 {args.expected} 条，实际 {len(result)} 条")
    output = Path(args.output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"collection": args.collection, "count": len(result), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
