"""Build a portable, offline slide gallery from extraction output."""

import html
import json
import math
from pathlib import Path
import re
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


def build_viewer(output: Path, *, title: str | None = None, source: str | None = None) -> Path:
    """Write index.html beside slides.json; image paths must stay inside output.

    Invalid manifests raise ValueError; a missing transcript is simply unavailable.
    Slide inputs and raw transcript.json are preserved. Also writes lecture.md,
    lecture-aligned.json, and readable transcript.txt. No network is needed.
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
    data = json.dumps({"slides": slides, "segments": lecture["paragraphs"],
                       "source": source, "duration": duration},
                      ensure_ascii=True, allow_nan=False)
    # Script elements are raw text, even when their type is application/json.
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    values = {"__TITLE__": html.escape(title), "__DATA__": data}
    document = re.sub(r"__TITLE__|__DATA__", lambda match: values[match[0]], _HTML)
    destination = output / "index.html"
    destination.write_text(document, encoding="utf-8")
    write_lecture(output, lecture)
    return destination


_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:dark;--bg:#10151e;--panel:#192230;--ink:#edf3ff;--muted:#a6b6cb;--accent:#8ad8cf;--line:#334258;font:16px/1.5 system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink)}button,a,summary{-webkit-tap-highlight-color:transparent}button,summary{cursor:pointer}button{font:inherit;color:inherit;background:var(--panel);border:1px solid var(--line);border-radius:.6rem;padding:.5rem .9rem}button:hover{border-color:var(--accent)}:focus-visible{outline:3px solid var(--accent);outline-offset:3px}a{color:var(--accent)}[hidden]{display:none!important}
header{padding:2rem clamp(1rem,4vw,4rem) 1rem}h1{margin:0;font-size:clamp(1.5rem,3vw,2.5rem);overflow-wrap:anywhere}header p{color:var(--muted);margin:.5rem 0}.layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(270px,340px);gap:1.5rem;padding:1rem clamp(1rem,4vw,4rem) 3rem}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,240px),1fr));gap:1.2rem;align-content:start}.card{padding:0;overflow:hidden;text-align:left;box-shadow:0 6px 20px #0003;transition:transform .15s}.card:hover{transform:translateY(-3px)}.card[aria-current=true]{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent)}.card img{display:block;width:100%;aspect-ratio:16/9;object-fit:contain;background:#080c12}.card span{display:block;padding:.7rem 1rem;color:var(--muted);font-size:.9rem}.card strong{color:var(--ink);margin-right:.7rem}
aside{min-width:0}.transcript{border:1px solid var(--line);border-radius:.8rem;background:var(--panel);overflow:hidden;position:sticky;top:1rem}.transcript summary{padding:.9rem 1rem;font-weight:600}.reading{overflow:auto;height:65vh;overscroll-behavior:contain;scrollbar-gutter:stable;padding:.4rem;scroll-behavior:auto}.segment{display:block;width:100%;border:0;border-radius:.4rem;background:transparent;text-align:left;padding:.7rem;white-space:normal;overflow-wrap:anywhere}.segment time{display:block;color:var(--accent);font-size:.75rem;font-weight:600;margin-bottom:.4rem}.segment{line-height:1.75}.segment+.segment{margin-top:.25rem}.segment[aria-current=true]{background:#28434a;box-shadow:inset 3px 0 var(--accent)}.empty{padding:1rem;color:var(--muted)}.source-row{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;padding:.5rem 0}.status{color:var(--muted)}
dialog{width:calc(100vw - 2rem);height:calc(100dvh - 2rem);max-width:none;max-height:none;padding:1rem;border:1px solid var(--line);border-radius:1rem;background:var(--bg);color:var(--ink)}dialog::backdrop{background:#000d;backdrop-filter:blur(5px)}body.modal-open{overflow:hidden}.modal-shell{height:100%;display:flex;flex-direction:column}.toolbar{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;padding-bottom:.8rem}.toolbar h2{font-size:1rem;margin:0 auto 0 0}.modal-body{display:grid;grid-template-columns:minmax(0,1fr) minmax(270px,340px);gap:1rem;min-height:0;flex:1}.slide-column{display:flex;flex-direction:column;min-height:0;gap:.65rem}.image-stage{display:flex;flex:1;align-items:center;justify-content:center;min-height:0;background:#080c12;border-radius:.6rem}.slide-progress{padding:.1rem .3rem .2rem}.timeline{position:relative;display:flex;height:.55rem;gap:2px;overflow:hidden;border-radius:1rem;background:#080c12}.timeline::after{content:'';position:absolute;left:var(--position,0%);top:0;bottom:0;width:2px;background:var(--ink)}.timeline span{min-width:0;background:#334258}.timeline span.past{background:var(--accent)}.timeline span.current{background:#28434a;box-shadow:inset 0 0 0 1px var(--accent)}.progress-label{font-size:.75rem;color:var(--muted);display:flex;justify-content:space-between;margin-top:.35rem}.image-stage img{width:100%;height:100%;object-fit:contain}.modal-body aside{min-height:0}.modal-body .transcript{position:static;max-height:100%}.modal-body .reading{height:calc(100dvh - 12rem)}
@media(min-width:761px){.layout:has(#transcript:not([open])),.modal-body:has(#transcript:not([open])){grid-template-columns:minmax(0,1fr) max-content}}
@media(max-width:760px){.layout,.modal-body{grid-template-columns:1fr}.layout{padding:1rem}.transcript{position:static}.reading{height:45vh}dialog{padding:.7rem;width:calc(100vw - 1rem);height:calc(100dvh - 1rem)}.modal-body{overflow:auto;display:flex;flex-direction:column}.slide-column{flex:none}.image-stage{flex:none;height:55dvh}.modal-body .reading{height:35dvh}.toolbar h2{width:100%}.toolbar button{padding:.4rem .6rem}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body>
<header><h1>__TITLE__</h1><p id="overview"></p><div class="source-row"><span class="status" id="gallery-status" aria-live="polite"></span><a id="gallery-source" target="_blank" rel="noopener noreferrer" hidden>Watch on YouTube ↗</a></div></header>
<main class="layout"><section class="grid" id="grid" aria-label="Slides"></section><aside id="gallery-panel"><details class="transcript" id="transcript" open><summary>Transcript</summary><div class="reading" id="reading" tabindex="0" aria-label="Scrollable transcript"></div></details></aside></main>
<dialog id="viewer" aria-labelledby="modal-title"><div class="modal-shell"><div class="toolbar"><h2 id="modal-title">Slide viewer</h2><button id="previous" aria-label="Previous slide (Left or Up arrow)">← Previous</button><button id="next" aria-label="Next slide (Right or Down arrow)">Next →</button><a id="modal-source" target="_blank" rel="noopener noreferrer" hidden>Watch on YouTube ↗</a><button id="close" aria-label="Close slide viewer (Escape)">Close ✕</button></div><div class="modal-body"><div class="slide-column"><div class="image-stage"><img id="large" alt=""></div><footer class="slide-progress"><div class="timeline" id="timeline" role="progressbar" aria-label="Lecture time at selected slide" aria-valuemin="0" aria-valuemax="100"></div><div class="progress-label"><span id="progress-time"></span><span id="progress-percent"></span></div></footer></div><aside id="modal-panel"></aside></div></div></dialog>
<script id="viewer-data" type="application/json">__DATA__</script>
<script>
'use strict';
const {slides,segments,source,duration}=JSON.parse(document.getElementById('viewer-data').textContent);
const $=id=>document.getElementById(id);
const dialog=$('viewer'), reading=$('reading'), transcript=$('transcript');
let selected=-1, highlighted=-1, trigger=null, programmedTop=null, scrollFrame=0, pendingSeek=null;
const cards=[], lines=[], timeline=[];
function clock(value){const n=Math.floor(value);return [Math.floor(n/3600),Math.floor(n/60)%60,n%60].map(x=>String(x).padStart(2,'0')).join(':');}
$('overview').textContent=`${slides.length} slides · ${segments.length ? 'Read along or open a slide to explore' : 'Transcript unavailable'}`;
for(const [i,slide] of slides.entries()){
 const button=document.createElement('button');button.className='card';button.setAttribute('aria-label',`Open slide ${i+1} at ${clock(slide.timestamp_seconds)}`);
 const img=document.createElement('img');img.src=slide.url;img.alt=`Slide ${i+1}`;img.loading='lazy';img.decoding='async';
 const caption=document.createElement('span'),number=document.createElement('strong');number.textContent=`${i+1}`;caption.append(number,document.createTextNode(clock(slide.timestamp_seconds)));
 button.append(img,caption);button.addEventListener('click',()=>openSlide(i,button));$('grid').append(button);cards.push(button);
 const span=document.createElement('span');const start=i===0?0:slide.stable_since_seconds,end=slides[i+1]?.stable_since_seconds??duration;
 span.style.flexGrow=String(Math.max(0,end-start));span.style.flexBasis='0';span.title=`Slide ${i+1}: ${clock(start)}–${clock(end)}`;
 $('timeline').append(span);timeline.push(span);
}
for(const [i,segment] of segments.entries()){
 const button=document.createElement('button');button.className='segment';
 button.dataset.start=String(segment.start_seconds);
 if(segment.timestamp){const time=document.createElement('time');time.textContent=clock(segment.start_seconds);time.title=segment.slide_index===null?'Transcript':`Slide ${segment.slide_index+1}`;button.append(time);}
 const text=document.createElement('span');text.textContent=segment.text;button.append(text);
 button.addEventListener('click',()=>{select(segment.slide_index,false);highlight(i);});reading.append(button);lines.push(button);
}
if(!segments.length){const message=document.createElement('p');message.className='empty';message.textContent='No transcript available for this lecture.';reading.append(message);}
if(!slides.length){const message=document.createElement('p');message.className='empty';message.textContent='No slides available.';$('grid').append(message);}
function segmentAt(time){let index=segments.findIndex(s=>s.end_seconds>time);return index<0 ? segments.length-1 : index;}
function highlight(index){if(index===highlighted)return;lines[highlighted]?.setAttribute('aria-current','false');lines[index]?.setAttribute('aria-current','true');highlighted=index;}
function seekTranscript(time){
 let i=segments.findIndex(segment=>segment.slide_index===selected);if(i<0)i=segmentAt(time);
 highlight(i);if(i<0)return;
 if(!transcript.open){pendingSeek=time;return;}pendingSeek=null;
 // Instant local scrolling avoids smooth-scroll feedback and never moves the page.
 reading.scrollTop+=lines[i].getBoundingClientRect().top-reading.getBoundingClientRect().top-8;
 programmedTop=reading.scrollTop;
}
function select(index,seek=true){
 if(!slides.length)return;
 index=Math.max(0,Math.min(slides.length-1,index));
 if(index===selected){if(seek)seekTranscript(slides[index].stable_since_seconds);return;}
 cards[selected]?.setAttribute('aria-current','false');selected=index;const slide=slides[selected];
 cards[selected].setAttribute('aria-current','true');
 if(!seek && !dialog.open)cards[selected].scrollIntoView({block:'nearest',behavior:'instant'});
 const label=`Slide ${selected+1} of ${slides.length} · ${clock(slide.timestamp_seconds)}`;
 $('gallery-status').textContent=label;$('modal-title').textContent=label;
 $('large').src=slide.url;$('large').alt=`Slide ${selected+1}`;
 $('previous').disabled=selected===0;$('next').disabled=selected===slides.length-1;
 const position=slide.stable_since_seconds,percent=duration>0?Math.min(100,100*position/duration):0;
 timeline.forEach((part,i)=>part.className=i<selected?'past':i===selected?'current':'');
 $('timeline').style.setProperty('--position',percent+'%');
 $('timeline').setAttribute('aria-valuenow',String(percent));$('timeline').setAttribute('aria-valuetext',`${clock(position)} of ${clock(duration)}`);
 $('progress-time').textContent=`${clock(position)} / ${clock(duration)}`;$('progress-percent').textContent=`${Math.round(percent)}%`;
 for(const id of ['gallery-source','modal-source']){const link=$(id);link.hidden=!source;if(source)link.href=source+'&t='+Math.floor(slide.timestamp_seconds)+'s';}
 if(seek)seekTranscript(slide.stable_since_seconds);
}
function moveTranscript(destination){const top=reading.scrollTop;$(destination).append(transcript);reading.scrollTop=top;programmedTop=reading.scrollTop;}
function openSlide(index,button){trigger=button;dialog.showModal();document.body.classList.add('modal-open');moveTranscript('modal-panel');select(index);$('close').focus();}
$('close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('close',()=>{moveTranscript('gallery-panel');document.body.classList.remove('modal-open');if(trigger?.isConnected)trigger.focus({preventScroll:true});});
$('previous').addEventListener('click',()=>select(selected-1));$('next').addEventListener('click',()=>select(selected+1));
// Programmatic scroll events are ignored by position, not a timer that can swallow user input.
transcript.addEventListener('toggle',()=>{if(!transcript.open)pendingSeek=slides[selected]?.stable_since_seconds??null;else if(pendingSeek!==null)seekTranscript(pendingSeek);});
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
 const target=event.target;
 if(target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"])'))return;
 if(dialog.open && event.key==='Tab'){
 const focusable=[...dialog.querySelectorAll('button:not(:disabled),a[href],summary,[tabindex="0"]')].filter(node=>node.getClientRects().length);
 const first=focusable[0],last=focusable[focusable.length-1];
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
 else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}return;
 }
 // In the modal arrows navigate slides, including when transcript text has focus.
 if(!dialog.open && target.closest('#transcript'))return;
 if(!dialog.open && !target.closest('#grid'))return;
 if(['ArrowLeft','ArrowDown','ArrowUp','ArrowRight'].includes(event.key)){
 event.preventDefault();const delta=['ArrowLeft','ArrowUp'].includes(event.key)?-1:1;
 const index=!dialog.open ? cards.indexOf(target.closest('.card')) : selected;select(index+delta);
 if(!dialog.open)cards[selected]?.focus();
 }
});
select(0);
</script></body></html>
'''
