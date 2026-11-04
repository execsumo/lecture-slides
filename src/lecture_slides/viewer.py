"""Build a portable, offline slide gallery from extraction output."""

from copy import deepcopy
import html
import json
import math
from pathlib import Path
import re
import tempfile
import zipfile
from urllib.parse import parse_qs, quote, urlsplit

from .alignment import align_lecture, write_lecture


def _seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("timestamps must be finite, nonnegative numbers")
    return value


def _youtube(source):
    """Return a canonical URL, never an unchecked user-supplied URL."""
    if not isinstance(source, str):
        return None
    try:
        url = urlsplit(source)
        if url.scheme not in ("http", "https") or url.username or url.password:
            return None
        host = url.hostname
        if host in ("youtu.be", "www.youtu.be"):
            video = url.path.strip("/")
        elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
            if url.path == "/watch":
                video = parse_qs(url.query).get("v", [""])[0]
            elif url.path.startswith(("/embed/", "/shorts/", "/live/")):
                video = url.path.split("/")[2]
            else:
                return None
        else:
            return None
        if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", video):
            return "https://www.youtube.com/watch?v=" + video
    except ValueError:
        pass
    return None


def _write_export(output, slides, lecture, name):
    """Write a self-contained zip: lecture.md (readable), lecture.json (machine-readable) and slide images.

    Images are renamed slides/001.ext (sequence order) and every reference is rewritten to match.
    The zip is built here because browsers cannot read local image files from a file:// page.
    """
    destination = output / "lecture-export.zip"
    if not slides or not all((output / slide["file"]).is_file() for slide in slides):
        destination.unlink(missing_ok=True)  # never ship (or keep a stale) incomplete package
        return False
    packaged = deepcopy(lecture)
    names = []
    for index, (slide, section) in enumerate(zip(slides, packaged["slides"]), 1):
        names.append(f"slides/{index:03d}{Path(slide['file']).suffix.lower()}")
        section["image"] = "./" + names[-1]
    temporary = destination.with_suffix(".zip.tmp")
    with tempfile.TemporaryDirectory() as scratch, zipfile.ZipFile(temporary, "w") as archive:
        write_lecture(scratch, packaged)
        # Deliberately minimal for LLM hand-off: the full text exists exactly once in each form.
        markdown = (Path(scratch) / "lecture.md").read_text(encoding="utf-8").replace(
            "[transcript.json](transcript.json)", "transcript.json")  # raw file is not packaged
        archive.writestr(f"{name}/lecture.md", markdown, zipfile.ZIP_DEFLATED)
        archive.write(Path(scratch) / "lecture-aligned.json", f"{name}/lecture.json", zipfile.ZIP_DEFLATED)
        for slide, archive_name in zip(slides, names):
            archive.write(output / slide["file"], f"{name}/{archive_name}", zipfile.ZIP_STORED)  # PNGs are compressed
    temporary.replace(destination)
    return True


def build_viewer(output: Path, *, title: str | None = None, source: str | None = None) -> Path:
    """Write index.html beside slides.json; image paths must stay inside output.

    Invalid manifests raise ValueError; a missing transcript is simply unavailable.
    Slide inputs and raw transcript.json are preserved. Also writes lecture.md,
    lecture-aligned.json, readable transcript.txt and a self-contained lecture-export.zip.
    """
    output = Path(output)
    manifest = json.loads((output / "slides.json").read_text(encoding="utf-8"))
    slides = []
    root = output.resolve()
    for slide in manifest["slides"]:
        filename = slide["file"]
        if not isinstance(filename, str) or not filename or "\\" in filename or "\0" in filename:
            raise ValueError("invalid slide path")
        path = Path(filename)
        if path.is_absolute() or ".." in path.parts or not (root / path).resolve().is_relative_to(root):
            raise ValueError("slide path must remain within output directory")
        if not path.name or path == Path("."):
            raise ValueError("invalid slide path")
        slides.append({"file": filename, "url": "./" + quote(path.as_posix(), safe="/"),
                       "timestamp_seconds": _seconds(slide["timestamp_seconds"]),
                       "stable_since_seconds": _seconds(slide["stable_since_seconds"])})
    slides.sort(key=lambda slide: slide["stable_since_seconds"])
    transcript_path = output / "transcript.json"
    transcript = json.loads(transcript_path.read_text(encoding="utf-8")) if transcript_path.exists() else {}
    segments = []
    for segment in transcript.get("segments", []):
        start, end = _seconds(segment["start_seconds"]), _seconds(segment["end_seconds"])
        if end < start or not isinstance(segment["text"], str):
            raise ValueError("invalid transcript segment")
        segments.append({"start_seconds": start, "end_seconds": end, "text": segment["text"]})
    segments.sort(key=lambda segment: segment["start_seconds"])
    title = title if title is not None else transcript.get("title") or output.name or "Lecture slides"
    source = _youtube(source if source is not None else manifest.get("source"))
    metadata_path = output / "lecture.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    duration = max([0, *(_seconds(value) for value in
                        (manifest.get("last_sample_seconds"), metadata.get("duration")) if value is not None),
                    *(s["timestamp_seconds"] for s in slides),
                    *(s["stable_since_seconds"] for s in slides),
                    *(s["end_seconds"] for s in segments)])
    lecture = align_lecture(slides, segments, title=title, source=source, duration=duration)
    export_name = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or "lecture"
    exported = _write_export(output, slides, lecture, export_name)
    data = json.dumps({"slides": slides, "segments": lecture["paragraphs"],
                       "source": source, "duration": duration, "export": exported},
                      ensure_ascii=True, allow_nan=False)
    # Script elements are raw text, even when their type is application/json.
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    values = {"__TITLE__": html.escape(title), "__DATA__": data, "__EXPORT__": export_name + ".zip"}
    document = re.sub(r"__TITLE__|__DATA__|__EXPORT__", lambda match: values[match[0]], _HTML)
    destination = output / "index.html"
    destination.write_text(document, encoding="utf-8")
    write_lecture(output, lecture)
    return destination


_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f3f5f9;--surface:#fff;--surface-2:#eef1f6;--ink:#162033;--muted:#5d6b82;--line:#dce2ec;--accent:#0f766e;--accent-ink:#fff;--accent-soft:#d6efec;--stage:#e6eaf1;--shadow:0 1px 2px #1620331a,0 4px 16px #16203314;--left:244px;--right:372px;color-scheme:light;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
:root[data-theme=dark]{--bg:#0d121a;--surface:#151c28;--surface-2:#1c2533;--ink:#e8eef8;--muted:#98a8bf;--line:#273246;--accent:#6fd3c8;--accent-ink:#06211e;--accent-soft:#1d3a3e;--stage:#090d13;--shadow:0 1px 2px #0006,0 4px 16px #0005;color-scheme:dark}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]):not([data-theme=dark]){--bg:#0d121a;--surface:#151c28;--surface-2:#1c2533;--ink:#e8eef8;--muted:#98a8bf;--line:#273246;--accent:#6fd3c8;--accent-ink:#06211e;--accent-soft:#1d3a3e;--stage:#090d13;--shadow:0 1px 2px #0006,0 4px 16px #0005;color-scheme:dark}}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;display:grid;grid-template-rows:auto minmax(0,1fr);background:var(--bg);color:var(--ink);overflow:hidden}
button,a{-webkit-tap-highlight-color:transparent}button{font:inherit;color:inherit;cursor:pointer;background:transparent;border:1px solid transparent;border-radius:.55rem}button:disabled{opacity:.4;cursor:default}:focus-visible{outline:2px solid var(--accent);outline-offset:2px}a{color:var(--accent)}[hidden]{display:none!important}
.topbar{display:flex;align-items:center;gap:.75rem;min-width:0;padding:.55rem .9rem;background:var(--surface);border-bottom:1px solid var(--line)}
.icon-btn{text-decoration:none;display:inline-grid;place-items:center;width:2rem;height:2rem;flex:none;color:var(--muted);opacity:.75}.icon-btn:hover{opacity:1}.icon-btn:hover{background:var(--surface-2);color:var(--ink)}.icon-btn svg{width:1.25rem;height:1.25rem;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.heading{min-width:0;flex:1;display:flex;align-items:center;gap:.7rem}.heading h1{margin:0;min-width:0;font-size:1.05rem;line-height:1.3;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.source{flex:none;display:inline-flex;align-items:center;gap:.4rem;font-size:.82rem;font-weight:600;text-decoration:none;padding:.2rem .5rem;color:var(--muted);border-radius:.5rem}.source svg{width:1.05rem;height:1.05rem;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.source:hover{background:var(--surface-2);color:var(--ink)}
.theme{display:inline-flex;flex:none;padding:2px;gap:2px;background:var(--surface-2);border:1px solid var(--line);border-radius:.65rem}.theme button{display:grid;place-items:center;width:1.9rem;height:1.9rem;padding:0;color:var(--muted);border-radius:.45rem}.theme svg{width:1.05rem;height:1.05rem;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.theme button[aria-pressed=true]{background:var(--surface);color:var(--ink);box-shadow:var(--shadow)}
.app{position:relative;overflow:hidden;display:grid;grid-template-columns:var(--left-w) minmax(0,1fr) var(--right-w);min-height:0;transition:grid-template-columns .22s ease;--left-w:var(--left);--right-w:var(--right)}
.app[data-left=closed]{--left-w:0px}.app[data-right=closed]{--right-w:0px}
.panel{min-width:0;min-height:0;overflow:hidden;background:var(--surface);transition:visibility .22s}.panel>.inner{display:flex;flex-direction:column;height:100%}
.panel.left{border-right:1px solid var(--line)}.panel.left>.inner{width:var(--left)}.panel.right{border-left:1px solid var(--line)}.panel.right>.inner{width:var(--right)}
.app[data-left=closed] .left,.app[data-right=closed] .right{visibility:hidden;border-width:0}
.panel-title{padding:.7rem .9rem .5rem;font-size:.72rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.thumbs{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;padding:.25rem .65rem 1rem;display:flex;flex-direction:column;gap:.5rem}
.card{display:block;width:100%;padding:.35rem;text-align:left;border:1px solid var(--line);background:var(--surface-2);border-radius:.7rem;flex:none}.card:hover{border-color:var(--muted)}.card[aria-current=true]{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent);background:var(--accent-soft)}
.card img{display:block;width:100%;aspect-ratio:16/9;object-fit:contain;background:var(--stage);border-radius:.4rem}.card span{display:flex;justify-content:space-between;padding:.3rem .2rem 0;font-size:.74rem;color:var(--muted)}.card strong{color:var(--ink);font-weight:650}
.main{min-width:0;min-height:0;display:flex;flex-direction:column;padding:.9rem 1rem .8rem;gap:.7rem}
.stage{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;background:var(--stage);border:1px solid var(--line);border-radius:.9rem;overflow:hidden;box-shadow:var(--shadow)}.stage img{display:block;width:100%;height:100%;object-fit:contain}.stage .empty{color:var(--muted)}
.controls{display:flex;align-items:center;gap:.7rem}.controls .nav{display:inline-flex;align-items:center;gap:.3rem;padding:.35rem .7rem;color:var(--muted);font-size:.9rem}.controls .nav:hover:not(:disabled){background:var(--surface-2);color:var(--ink)}.slide-label{flex:1;text-align:center;font-variant-numeric:tabular-nums;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.slide-label small{font-weight:400;color:var(--muted);margin-left:.5rem}
.timeline{position:relative;display:flex;height:.7rem;gap:2px;overflow:hidden;border-radius:1rem;background:var(--surface-2);cursor:pointer}.timeline::after{content:'';position:absolute;left:var(--position,0%);top:0;bottom:0;width:2px;background:var(--ink);pointer-events:none}.timeline span{min-width:0;background:var(--line)}.timeline span:hover{filter:brightness(.9)}.timeline span.past{background:var(--accent);opacity:.75}.timeline span.current{background:var(--accent)}
.progress-label{display:flex;justify-content:space-between;margin-top:.3rem;font-size:.75rem;color:var(--muted);font-variant-numeric:tabular-nums}
.reading{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding:.2rem .5rem 1.5rem}.segment{display:block;width:100%;padding:.65rem .75rem;margin-top:.15rem;text-align:left;line-height:1.7;white-space:normal;overflow-wrap:anywhere;border-radius:.6rem}.segment:hover{background:var(--surface-2)}.segment time{display:block;margin-bottom:.25rem;font-size:.72rem;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums}.segment[aria-current=true]{background:var(--accent-soft);box-shadow:inset 3px 0 var(--accent)}.empty{padding:1rem;color:var(--muted)}
.scrim{display:none}
@media(max-width:900px){.app{display:block}.panel{position:absolute;top:0;bottom:0;z-index:5;width:min(86vw,360px);box-shadow:var(--shadow);transition:transform .22s,visibility .22s}.panel.left{left:0;transform:translateX(0)}.panel.right{right:0;transform:translateX(0)}.panel.left>.inner,.panel.right>.inner{width:100%}.app[data-left=closed] .left{transform:translateX(-100%)}.app[data-right=closed] .right{transform:translateX(100%)}.app:not([data-left=closed]) .scrim,.app:not([data-right=closed]) .scrim{display:block;position:absolute;inset:0;z-index:4;background:#0007}.main{height:100%;padding:.6rem}.source{padding:.25rem .4rem}.source{font-size:0;gap:0}.controls .nav .word{display:none}}
@media(max-width:560px){.theme button{padding:.25rem .45rem}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body>
<header class="topbar">
<button class="icon-btn" id="toggle-left" aria-controls="left" aria-expanded="true" aria-label="Toggle slide list ([)" title="Slide list ( [ )"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg></button>
<div class="heading"><h1 title="__TITLE__">__TITLE__</h1><a class="source" id="source" target="_blank" rel="noopener noreferrer" hidden title="Watch on YouTube"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M8 2l4 4 4-4"/></svg>Watch</a></div>
<div class="theme" role="group" aria-label="Color theme"><button data-theme-choice="light" aria-pressed="false" aria-label="Light theme" title="Light"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></button><button data-theme-choice="system" aria-pressed="true" aria-label="System theme" title="System"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg></button><button data-theme-choice="dark" aria-pressed="false" aria-label="Dark theme" title="Dark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg></button></div>
<a class="icon-btn" id="export-btn" hidden href="./lecture-export.zip" download="__EXPORT__" aria-label="Download lecture package (zip: slides, transcript, Markdown, JSON)" title="Download package (zip)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 20h14"/></svg></a>
<button class="icon-btn" id="toggle-right" aria-controls="right" aria-expanded="true" aria-label="Toggle transcript (])" title="Transcript ( ] )"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/></svg></button>
</header>
<div class="app" id="app" data-left="open" data-right="open">
<nav class="panel left" id="left" aria-label="Slides"><div class="inner"><div class="panel-title"><span id="slide-count"></span> Slides</div><div class="thumbs" id="thumbs"></div></div></nav>
<main class="main"><div class="stage" id="stage"><img id="large" alt="" hidden></div>
<div><div class="controls"><button class="nav" id="previous" aria-label="Previous slide (Left or Up arrow)">← <span class="word">Previous</span></button><div class="slide-label" id="slide-label" aria-live="polite"></div><button class="nav" id="next" aria-label="Next slide (Right or Down arrow)"><span class="word">Next</span> →</button></div>
<div style="height:.6rem"></div><div class="timeline" id="timeline" role="progressbar" aria-label="Lecture time at selected slide" aria-valuemin="0" aria-valuemax="100"></div><div class="progress-label"><span id="progress-time"></span><span id="progress-percent"></span></div></div></main>
<aside class="panel right" id="right" aria-label="Transcript"><div class="inner"><div class="panel-title">Transcript</div><div class="reading" id="reading" tabindex="0" aria-label="Scrollable transcript"></div></div></aside>
<div class="scrim" id="scrim"></div>
</div>
<script id="viewer-data" type="application/json">__DATA__</script>
<script>
'use strict';
const {slides,segments,source,duration,export:exported}=JSON.parse(document.getElementById('viewer-data').textContent);
const $=id=>document.getElementById(id);
const app=$('app'), reading=$('reading'), thumbs=$('thumbs'), root=document.documentElement;
let selected=-1, highlighted=-1, programmedTop=null, scrollFrame=0;
const cards=[], lines=[], timeline=[];
function clock(value){const n=Math.floor(value);return [Math.floor(n/3600),Math.floor(n/60)%60,n%60].map(x=>String(x).padStart(2,'0')).join(':');}
/* Theme: light / system / dark. System leaves data-theme unset so the CSS media query decides. */
function setTheme(choice,save=true){
 if(choice==='light'||choice==='dark')root.dataset.theme=choice;else{choice='system';delete root.dataset.theme;}
 document.querySelectorAll('[data-theme-choice]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.themeChoice===choice)));
 if(save){try{localStorage.setItem('lecture-slides-theme',choice);}catch(e){}}
}
document.querySelectorAll('[data-theme-choice]').forEach(b=>b.addEventListener('click',()=>setTheme(b.dataset.themeChoice)));
let remembered=null;try{remembered=localStorage.getItem('lecture-slides-theme');}catch(e){}
setTheme(remembered,false);
$('export-btn').hidden=!exported;
$('slide-count').textContent=slides.length;
for(const [i,slide] of slides.entries()){
 const button=document.createElement('button');button.className='card';button.setAttribute('aria-label',`Slide ${i+1} at ${clock(slide.timestamp_seconds)}`);
 const img=document.createElement('img');img.src=slide.url;img.alt='';img.loading='lazy';img.decoding='async';
 const caption=document.createElement('span'),number=document.createElement('strong'),when=document.createElement('em');number.textContent=`${i+1}`;when.textContent=clock(slide.timestamp_seconds);when.style.fontStyle='normal';caption.append(number,when);
 button.append(img,caption);button.addEventListener('click',()=>select(i));thumbs.append(button);cards.push(button);
 const span=document.createElement('span');const start=i===0?0:slide.stable_since_seconds,end=slides[i+1]?.stable_since_seconds??duration;
 span.style.flexGrow=String(Math.max(0,end-start));span.style.flexBasis='0';span.title=`Slide ${i+1}: ${clock(start)}–${clock(end)}`;
 span.addEventListener('click',()=>select(i));$('timeline').append(span);timeline.push(span);
}
for(const [i,segment] of segments.entries()){
 const button=document.createElement('button');button.className='segment';
 button.dataset.start=String(segment.start_seconds);
 if(segment.timestamp){const time=document.createElement('time');time.textContent=clock(segment.start_seconds);time.title=segment.slide_index===null?'Transcript':`Slide ${segment.slide_index+1}`;button.append(time);}
 const text=document.createElement('span');text.textContent=segment.text;button.append(text);
 button.addEventListener('click',()=>{select(segment.slide_index,false);highlight(i);});reading.append(button);lines.push(button);
}
if(!segments.length){const message=document.createElement('p');message.className='empty';message.textContent='No transcript available for this lecture.';reading.append(message);}
if(!slides.length){const message=document.createElement('p');message.className='empty';message.textContent='No slides available.';$('stage').append(message);$('timeline').hidden=true;}
function segmentAt(time){let index=segments.findIndex(s=>s.end_seconds>time);return index<0 ? segments.length-1 : index;}
function highlight(index){if(index===highlighted)return;lines[highlighted]?.setAttribute('aria-current','false');lines[index]?.setAttribute('aria-current','true');highlighted=index;}
function seekTranscript(time){
 let i=segments.findIndex(segment=>segment.slide_index===selected);if(i<0)i=segmentAt(time);
 highlight(i);if(i<0)return;
 // Instant local scrolling avoids smooth-scroll feedback and never moves the page.
 reading.scrollTop+=lines[i].getBoundingClientRect().top-reading.getBoundingClientRect().top-8;
 programmedTop=reading.scrollTop;
}
function revealThumb(card){
 const a=card.getBoundingClientRect(),b=thumbs.getBoundingClientRect();
 if(a.top<b.top+8)thumbs.scrollTop+=a.top-b.top-8;else if(a.bottom>b.bottom-8)thumbs.scrollTop+=a.bottom-b.bottom+8;
}
function select(index,seek=true){
 if(!slides.length)return;
 index=Math.max(0,Math.min(slides.length-1,index));
 if(index===selected){if(seek)seekTranscript(slides[index].stable_since_seconds);return;}
 cards[selected]?.setAttribute('aria-current','false');selected=index;const slide=slides[selected];
 cards[selected].setAttribute('aria-current','true');revealThumb(cards[selected]);
 $('slide-label').replaceChildren(document.createTextNode(`Slide ${selected+1} of ${slides.length}`));
 const when=document.createElement('small');when.textContent=clock(slide.timestamp_seconds);$('slide-label').append(when);
 $('large').hidden=false;$('large').src=slide.url;$('large').alt=`Slide ${selected+1}`;
 for(const n of [selected-1,selected+1])if(slides[n])new Image().src=slides[n].url;
 $('previous').disabled=selected===0;$('next').disabled=selected===slides.length-1;
 const position=slide.stable_since_seconds,percent=duration>0?Math.min(100,100*position/duration):0;
 timeline.forEach((part,i)=>part.className=i<selected?'past':i===selected?'current':'');
 $('timeline').style.setProperty('--position',percent+'%');
 $('timeline').setAttribute('aria-valuenow',String(percent));$('timeline').setAttribute('aria-valuetext',`${clock(position)} of ${clock(duration)}`);
 $('progress-time').textContent=`${clock(position)} / ${clock(duration)}`;$('progress-percent').textContent=`${Math.round(percent)}%`;
 $('source').hidden=!source;if(source)$('source').href=source+'&t='+Math.floor(slide.timestamp_seconds)+'s';
 if(seek)seekTranscript(slide.stable_since_seconds);
}
/* Collapsible side panels. Closed panels are inert; on narrow screens they are drawers and only one is open. */
const narrow=matchMedia('(max-width:900px)');
function setPanel(side,open){
 if(open&&narrow.matches)for(const other of ['left','right'])if(other!==side)setPanel(other,false);
 app.dataset[side]=open?'open':'closed';$(side).inert=!open;
 $('toggle-'+side).setAttribute('aria-expanded',String(open));
 if(open&&side==='right'&&selected>=0)seekTranscript(slides[selected].stable_since_seconds);
 if(open&&side==='left'&&selected>=0)revealThumb(cards[selected]);
}
const togglePanel=side=>setPanel(side,app.dataset[side]==='closed');
$('toggle-left').addEventListener('click',()=>togglePanel('left'));$('toggle-right').addEventListener('click',()=>togglePanel('right'));
$('scrim').addEventListener('click',()=>{setPanel('left',false);setPanel('right',false);});
if(narrow.matches){setPanel('left',false);setPanel('right',false);}else{setPanel('left',true);setPanel('right',innerWidth>=1180);}
narrow.addEventListener('change',()=>{if(narrow.matches){setPanel('left',false);setPanel('right',false);}});
/* Wheel over the centre column steps through slides; the side panels keep their own native scrolling.
   Deltas accumulate and a short lock turns one trackpad flick (or inertia tail) into a single step. */
let wheelSum=0,wheelLock=0;
document.querySelector('main').addEventListener('wheel',event=>{
 if(event.ctrlKey||event.metaKey||event.shiftKey||Math.abs(event.deltaY)<Math.abs(event.deltaX))return; // pinch-zoom, sideways swipes
 event.preventDefault();
 if(event.timeStamp<wheelLock)return;
 const unit=event.deltaMode===0?1:event.deltaMode===1?16:100;
 wheelSum+=event.deltaY*unit;
 if(Math.abs(wheelSum)<40)return;
 select(selected+(wheelSum>0?1:-1));wheelSum=0;wheelLock=event.timeStamp+280;
},{passive:false});
$('previous').addEventListener('click',()=>select(selected-1));$('next').addEventListener('click',()=>select(selected+1));
// Programmatic scroll events are ignored by position, not a timer that can swallow user input.
reading.addEventListener('scroll',()=>{
 if(programmedTop!==null && Math.abs(reading.scrollTop-programmedTop)<1)return;programmedTop=null;
 if(scrollFrame)return;scrollFrame=requestAnimationFrame(()=>{scrollFrame=0;if(!lines.length)return;
 const top=reading.getBoundingClientRect().top+12,atEnd=reading.scrollHeight-reading.clientHeight-reading.scrollTop<2;
 let index=atEnd?lines.length-1:lines.findIndex(line=>line.getBoundingClientRect().bottom>top);if(index<0)index=lines.length-1;
 select(segments[index].slide_index,false);highlight(index);
 });
});
document.addEventListener('keydown',event=>{
 if(event.defaultPrevented||event.altKey||event.ctrlKey||event.metaKey)return;
 if(event.target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"])'))return;
 const key=event.key;
 if(key==='['){togglePanel('left');return;}
 if(key===']'){togglePanel('right');return;}
 if(key==='Escape'&&narrow.matches&&(app.dataset.left==='open'||app.dataset.right==='open')){setPanel('left',false);setPanel('right',false);return;}
 // Arrow keys always change slides; PageUp/PageDown still scroll the transcript.
 if(['ArrowLeft','ArrowUp'].includes(key))select(selected-1);
 else if(['ArrowRight','ArrowDown'].includes(key))select(selected+1);
 else if(key==='Home')select(0);else if(key==='End')select(slides.length-1);
 else return;
 event.preventDefault();
});
select(0);
</script></body></html>
'''
