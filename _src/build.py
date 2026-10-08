import datetime
import html
import os
import re
import shutil
import subprocess
import sys

SITE_NAME = "lacedawn's blog"
SITE_URL = "[SITE_URL]"
HOME_COUNT = 7
FEED_COUNT = 20

MONTHS_FULL = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
MONTHS_SHORT = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
LINK_TAG = re.compile(r"<a\s[^<>]*>")

def script_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def pandoc_binary():
    found = shutil.which("pandoc")
    if found is not None:
        return found
    print("pandoc was not found on PATH, nothing was built")
    print("install it first, then run python3 _src/build.py again")
    print("macOS: brew install pandoc")
    print("windows: winget install pandoc.pandoc")
    print("debian/ubuntu: sudo apt update && sudo apt install pandoc")
    return None

def highlight_flag(binary):
    try:
        output = subprocess.run([binary, "--version"], capture_output=True, text=True).stdout
    except OSError:
        return "--no-highlight"
    match = re.search(r"pandoc\s+(\d+)\.(\d+)", output)
    if match and (int(match.group(1)), int(match.group(2))) >= (3, 8):
        return "--syntax-highlighting=none"
    return "--no-highlight"

def markdown_files(folder):
    return sorted(name for name in os.listdir(folder) if name.endswith(".md") and not name.startswith(("_", ".")))

def read_metadata(source_path):
    with open(source_path, "r", encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    if not lines or lines[0] != "---":
        return {}, "\n".join(lines)
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, "\n".join(lines)
    metadata = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
            value = value[1:-1]
        metadata[key.strip().lower()] = value
    return metadata, "\n".join(lines[end + 1:])

def convert(binary, flag, source_path, template_path, variables):
    command = [binary, "--from=markdown+smart", "--to=html5", "--standalone", "--template=" + template_path, "--wrap=none", flag]
    for key, value in variables:
        command += ["-V", key + "=" + value]
    try:
        finished = subprocess.run(command + [source_path], capture_output=True, text=True)
    except OSError as caught:
        return None, str(caught)
    if finished.returncode != 0:
        return None, finished.stderr.strip()
    return finished.stdout, ""

def external_rel(match):
    tag = match.group(0)
    if 'href="http://' not in tag and 'href="https://' not in tag:
        return tag
    if " rel=" in tag:
        return tag
    return tag[:-1] + ' rel="noopener noreferrer">'

def postprocess(page, source_label):
    page = LINK_TAG.sub(external_rel, page)
    marker = '<meta charset="utf-8">'
    return page.replace(marker, marker + '\n<meta name="generated-by" content="' + source_label + '">', 1)

def write_if_changed(path, content):
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            if handle.read().replace("\r\n", "\n").replace("\r", "\n") == content:
                return False
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return True

def replace_element(page, element_id, inner):
    opening = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)\b[^<>]*\bid=\"" + element_id + r"\"[^<>]*>")
    match = opening.search(page)
    if match is None:
        return None
    tag = match.group(1)
    closer = re.compile(r"<(/?)" + tag + r"\b[^<>]*>")
    depth = 1
    for tag_match in closer.finditer(page, match.end()):
        if tag_match.group(0).endswith("/>"):
            continue
        if tag_match.group(1):
            depth -= 1
        else:
            depth += 1
        if depth == 0:
            return page[:match.end()] + inner + page[tag_match.start():]
    return None

def home_inner(posts):
    items = ['<li><a href="writings/' + post["slug"] + '.html">' + html.escape(post["title"]) + "</a></li>" for post in posts[:HOME_COUNT]]
    return "\n" + "\n".join(items) + "\n" if items else ""

def archive_inner(posts):
    blocks = []
    for year in sorted({post["date"].year for post in posts}, reverse=True):
        items = []
        for post in posts:
            if post["date"].year != year:
                continue
            day = MONTHS_SHORT[post["date"].month - 1] + " " + str(post["date"].day)
            items.append('<li><time datetime="' + post["date"].isoformat() + '">' + day + '</time> - <a href="writings/' + post["slug"] + '.html">' + html.escape(post["title"]) + "</a></li>")
        blocks.append("<h2>" + str(year) + "</h2>\n<ul>\n" + "\n".join(items) + "\n</ul>")
    return "\n" + "\n".join(blocks) + "\n" if blocks else ""

def build_source(kind, root, binary, flag, name, problems, changed, posts):
    label = kind + "/" + name
    slug = name[:-3]
    if SLUG.fullmatch(slug) is None:
        problems.append("error: " + label + " has a bad slug, use lowercase letters, digits, single hyphens")
        return None
    source_path = os.path.join(root, "_src", kind, name)
    meta, body = read_metadata(source_path)
    if kind == "writings":
        needed, output_rel, template = ("title", "date", "description"), "writings/" + slug + ".html", os.path.join(root, "_src", "templates", "post.html")
    else:
        needed, output_rel, template = ("title",), slug + ".html", os.path.join(root, "_src", "templates", "page.html")
    missing = [key for key in needed if not meta.get(key)]
    if missing:
        problems.append("error: " + label + " is missing " + ", ".join(missing))
        return None
    if meta.get("draft", "").lower() == "true":
        if os.path.exists(os.path.join(root, output_rel)):
            problems.append("warning: draft " + label + " already has " + output_rel)
        return "draft"
    day = None
    if kind == "writings":
        try:
            day = datetime.date.fromisoformat(meta["date"])
        except ValueError:
            problems.append("error: " + label + " has a bad date, use YYYY-MM-DD")
            return None
    if any(line.startswith("# ") for line in body.split("\n")):
        problems.append("warning: " + label + " has a single # heading, the title comes from front matter")
    site = SITE_URL.rstrip("/")
    variables = [("site_name", html.escape(SITE_NAME, quote=True)), ("site_url", html.escape(SITE_URL, quote=True)), ("canonical_url", html.escape(site + "/" + output_rel, quote=True)), ("year", str(datetime.date.today().year))]
    if day is not None:
        display = MONTHS_FULL[day.month - 1] + " " + str(day.day) + ", " + str(day.year)
        variables += [("date_iso", day.isoformat()), ("date_display", display)]
    page, failure = convert(binary, flag, source_path, template, variables)
    if page is None:
        problems.append("error: " + label + " failed to convert: " + failure)
        return None
    if write_if_changed(os.path.join(root, output_rel), postprocess(page, "_src/" + kind + "/" + name)):
        changed.append(output_rel)
    if day is not None:
        posts.append({"slug": slug, "title": meta["title"], "date": day})
    return "built"

def refresh_list(root, filename, element_id, inner, problems, changed, optional):
    path = os.path.join(root, filename)
    with open(path, "r", encoding="utf-8") as handle:
        updated = replace_element(handle.read(), element_id, inner)
    if updated is None:
        problems.append("note: " + filename + " has no " + element_id + " yet, skipped" if optional else "error: " + filename + " is missing " + element_id)
        return
    if write_if_changed(path, updated):
        changed.append(filename)

def main():
    root = script_root()
    binary = pandoc_binary()
    if binary is None:
        return 1
    flag, problems, changed, posts = highlight_flag(binary), [], [], []
    counts, drafts = {"writings": 0, "pages": 0}, []
    for kind in ("writings", "pages"):
        folder = os.path.join(root, "_src", kind)
        if not os.path.isdir(folder):
            continue
        for name in markdown_files(folder):
            result = build_source(kind, root, binary, flag, name, problems, changed, posts)
            if result == "built":
                counts[kind] += 1
            elif result == "draft":
                drafts.append(kind + "/" + name)
    posts.sort(key=lambda post: (post["date"], post["title"]), reverse=True)
    refresh_list(root, "index.html", "writings-list", home_inner(posts), problems, changed, False)
    refresh_list(root, "archive.html", "archive-list", archive_inner(posts), problems, changed, True)
    for problem in problems:
        print(problem)
    summary = "built " + str(counts["writings"]) + " writings and " + str(counts["pages"]) + " pages"
    if drafts:
        summary += ", skipped drafts: " + ", ".join(drafts)
    summary += ", changed: " + ", ".join(sorted(changed)) if changed else ", nothing changed"
    print(summary)
    return 1 if any(problem.startswith("error:") for problem in problems) else 0

sys.exit(main())
