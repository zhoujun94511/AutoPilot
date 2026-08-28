"""Web 检视取源：从 WebDriver 拿「带边界 + 已在浏览器内校验唯一的定位符」的 DOM 树 + 截图。

面向 **Web 自动化用例编写**：宁可多保留可定位/可断言节点，也不为「页面整洁」过度裁剪。
与 Chrome F12 同页同源，但策略是自动化优先（可见交互控件、文案定位、data-testid 等），
不是 DevTools 的完整 DOM 镜像。

注入 JS 职责：
  1) 遍历 DOM（含 Shadow Root 开放影子树）→ getBoundingClientRect 边界（CSS 视口像素）；
  2) 采集自动化常用属性（含全部 data-*）与可定位文案（含子元素包裹的短文本）；
  3) 浏览器内校验唯一性后生成 loc{id,css,xpath}。
Python 侧 parse_web 直接采用已验证定位符，缺失时回退启发式。

坐标为 CSS 像素；截图为设备像素，面板按 innerWidth 与 dpr 换算点选。
"""

from __future__ import annotations

import json
from typing import Tuple

# 注入页面执行：遍历可见 DOM → 节点树（含 rect + 浏览器内校验过的 loc{id,css,xpath}）。
# 生成/校验内核移植自成熟书签脚本，去掉高亮徽标/CSV 下载等独立 UI 功能。
_SNAPSHOT_JS = r"""
const MAX_NODES = arguments[0] || 4000;
let count = 0;
let truncated = false;
const KEEP = ["id","name","class","type","role","placeholder","title",
              "href","value","data-testid","aria-label","alt","for","src","action"];
const INTERACTIVE = new Set(["a","button","input","select","textarea","label","option",
                             "summary","li","h1","h2","h3","h4","span"]);

function cssEscape(v){
  if (typeof CSS !== "undefined" && CSS.escape) return CSS.escape(v);
  return String(v).replace(/([!"#$%&'()*+,./:;<=>?@[\\\]^`{|}~])/g, "\\$1");
}
function xq(v){
  if (v.indexOf("'") === -1) return "'" + v + "'";
  return "concat('" + v.split("'").join("',\"'\",'") + "')";
}
function escAttr(v){ return v ? String(v).replace(/"/g, '\\"') : ""; }
function uniqId(id){
  if (!id) return false;
  try { return document.querySelectorAll("#" + cssEscape(id)).length === 1; }
  catch(e){ return false; }
}
function uniqXPath(xp, el){
  try {
    const r = document.evaluate(xp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
    return r.snapshotLength === 1 && r.snapshotItem(0) === el;
  } catch(e){ return false; }
}
function uniqCss(sel, el){
  try { const n = document.querySelectorAll(sel); return n.length === 1 && n[0] === el; }
  catch(e){ return false; }
}
function targetPredicate(el){
  const g = a => el.getAttribute(a);
  if (g("name")) return "[@name=" + xq(g("name")) + "]";
  if (g("role")) return "[@role=" + xq(g("role")) + "]";
  if (g("aria-label")) return "[@aria-label=" + xq(g("aria-label")) + "]";
  if (g("placeholder")) return "[@placeholder=" + xq(g("placeholder")) + "]";
  const t = (el.textContent || "").trim();
  if (t && t.length < 50 && t.indexOf("\n") === -1) return "[contains(string(.)," + xq(t) + ")]";
  return "";
}
function indexPredicate(el, parent){
  if (!parent) return "";
  let idx = 0, same = 0;
  for (const sib of parent.children){
    if (sib.tagName === el.tagName){ same++; if (sib === el){ idx = same; } }
  }
  return (same > 1 && idx > 0) ? "[" + idx + "]" : "";
}
function genXPath(el){
  const tag = el.tagName.toLowerCase();
  if (el.id && uniqId(el.id)) return "//*[@id=" + xq(el.id) + "]";
  const tp = targetPredicate(el);
  if (tp){ const p = "//" + tag + tp; if (uniqXPath(p, el)) return p; }
  // 最近唯一 id 祖先 + 相对
  let anc = el.parentElement;
  while (anc && anc !== document.documentElement){
    if (anc.id && uniqId(anc.id)){
      const p = "//*[@id=" + xq(anc.id) + "]//" + tag + (tp || "");
      if (uniqXPath(p, el)) return p;
      break;
    }
    anc = anc.parentElement;
  }
  // 完整索引路径兜底
  const segs = []; let cur = el;
  while (cur && cur.nodeType === 1 && cur !== document.documentElement){
    segs.unshift(cur.tagName.toLowerCase() + indexPredicate(cur, cur.parentElement));
    cur = cur.parentElement;
  }
  const full = "/" + (document.documentElement.tagName.toLowerCase()) + "/" + segs.join("/");
  return uniqXPath(full, el) ? full : "";
}
function genCss(el){
  const tag = el.tagName.toLowerCase();
  let s;
  if (el.id && uniqId(el.id)){ s = "#" + cssEscape(el.id); if (uniqCss(s, el)) return s; }
  const nm = el.getAttribute("name");
  if (nm){ s = tag + '[name="' + escAttr(nm) + '"]'; if (uniqCss(s, el)) return s;
           s = '[name="' + escAttr(nm) + '"]'; if (uniqCss(s, el)) return s; }
  const tid = el.getAttribute("data-testid");
  if (tid){ s = '[data-testid="' + escAttr(tid) + '"]'; if (uniqCss(s, el)) return s; }
  for (const c of el.classList){
    s = tag + "." + cssEscape(c); if (uniqCss(s, el)) return s;
    s = "." + cssEscape(c); if (uniqCss(s, el)) return s;
  }
  if (el.classList.length){
    const all = Array.from(el.classList).map(c => "." + cssEscape(c)).join("");
    s = tag + all; if (uniqCss(s, el)) return s;
  }
  for (const a of ["role","aria-label","placeholder","type"]){
    const v = el.getAttribute(a);
    if (v){ s = tag + "[" + a + '="' + escAttr(v) + '"]'; if (uniqCss(s, el)) return s; }
  }
  // 祖先锚定 nth-of-type 路径兜底
  const segs = []; let cur = el, ancSel = null;
  while (cur && cur.nodeType === 1 && cur !== document.documentElement){
    let seg = cur.tagName.toLowerCase();
    if (cur !== el && cur.id && uniqId(cur.id)){ ancSel = "#" + cssEscape(cur.id); break; }
    const parent = cur.parentElement;
    if (parent){
      const sib = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
      if (sib.length > 1) seg += ":nth-of-type(" + (sib.indexOf(cur) + 1) + ")";
    }
    segs.unshift(seg);
    cur = parent;
  }
  s = (ancSel ? ancSel + " > " : "") + segs.join(" > ");
  return uniqCss(s, el) ? s : "";
}

function automationRelevant(el){
  const tag = (el.tagName || "").toLowerCase();
  if (INTERACTIVE.has(tag)) return true;
  if (el.id || el.getAttribute("name") || el.getAttribute("data-testid")) return true;
  return false;
}
function hasBox(el){
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}
function collectAttrs(el){
  const attrs = {};
  for (const k of KEEP){
    const v = el.getAttribute && el.getAttribute(k);
    if (v) attrs[k] = v;
  }
  if (el.attributes){
    for (const a of el.attributes){
      const n = a.name;
      if (n && n.startsWith("data-") && a.value && !attrs[n]) attrs[n] = a.value;
    }
  }
  return attrs;
}
function collectText(el){
  let txt = "";
  for (const n of el.childNodes){ if (n.nodeType === 3) txt += n.nodeValue; }
  txt = txt.trim();
  if (txt) return txt.slice(0, 80);
  const tag = (el.tagName || "").toLowerCase();
  const full = (el.textContent || "").trim().replace(/\\s+/g, " ");
  if (!full || full.length > 80 || full.indexOf("\\n") !== -1) return "";
  // 子元素包文案（<a><span>登录</span></a>）或短按钮/链接文案——与 Selenium .text / 文案定位一致
  if (el.children.length === 0 || INTERACTIVE.has(tag)) return full;
  return "";
}
function visible(el){
  const s = window.getComputedStyle(el);
  if (s.display === "none") return false;
  if (hasBox(el)) return true;
  // 零尺寸容器：子树里仍有可交互节点则保留（百度顶栏等）
  for (const c of el.children){ if (visible(c)) return true; }
  if (el.shadowRoot){
    for (const c of el.shadowRoot.children){ if (visible(c)) return true; }
  }
  // 隐藏但仍常被 find_element 命中的表单控件（type=hidden 等）——避免写用例时「树里找不到」
  if (s.visibility === "hidden" && automationRelevant(el)) return true;
  return false;
}
function walk(el){
  if (count >= MAX_NODES){ truncated = true; return null; }
  const tag = (el.tagName || "").toLowerCase();
  if (tag === "script" || tag === "style" || tag === "noscript") return null;
  if (!visible(el)) return null;
  count++;
  const r = el.getBoundingClientRect();
  const attrs = collectAttrs(el);
  const txt = collectText(el);
  if (txt) attrs["text"] = txt;
  const loc = { id: (el.id && uniqId(el.id)) ? el.id : "", css: genCss(el), xpath: genXPath(el) };
  const node = {
    tag: tag, attrs: attrs,
    rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
    loc: loc, children: []
  };
  for (const c of el.children){ const cn = walk(c); if (cn) node.children.push(cn); }
  if (el.shadowRoot){
    for (const c of el.shadowRoot.children){ const cn = walk(c); if (cn) node.children.push(cn); }
  }
  return node;
}
const root = walk(document.documentElement) || {tag:"html", attrs:{}, rect:[0,0,0,0], loc:{}, children:[]};
return JSON.stringify({
  viewport: [window.innerWidth, window.innerHeight],
  dpr: window.devicePixelRatio || 1,
  tree: root,
  nodeCount: count,
  truncated: truncated
});
"""


def web_snapshot(driver, max_nodes: int = 4000) -> Tuple[bytes, str]:
    """返回 (截图 png, DOM 快照 JSON 串)。DOM JSON 形如
    {"viewport":[w,h],"dpr":r,"tree":{tag,attrs,rect,loc:{id,css,xpath},children}}，
    其中 loc 内的 css/xpath 已在浏览器内校验为唯一命中。"""
    raw = driver.execute_script(_SNAPSHOT_JS, max_nodes)
    payload = raw if isinstance(raw, str) else json.dumps(raw)
    png = driver.get_screenshot_as_png()
    return png, payload
