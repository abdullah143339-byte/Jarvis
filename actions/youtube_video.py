#youtube_video.py
import json
import re
import sys
import time
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from urllib.parse import quote_plus

try:
    import pyautogui
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import numpy as np
    _NUMPY = True
except ImportError:
    _NUMPY = False

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _TRANSCRIPT_OK = True
except ImportError:
    _TRANSCRIPT_OK = False

from config import get_os, is_windows, is_mac, is_linux


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_YT_VIDEO_FILTER = "EgIQAQ%3D%3D"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _open_url(url: str) -> None:
    try:
        if is_mac():
            subprocess.Popen(["open", url])
        elif is_linux():
            subprocess.Popen(["xdg-open", url])
        else:
            subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
    except Exception as e:
        print(f"[YouTube] ⚠️ open_url failed: {e}")

def _scrape_first_video_url(query: str) -> str | None:

    if not _REQUESTS_OK:
        return None

    search_url = (
        f"https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}"
        f"&sp={_YT_VIDEO_FILTER}"
    )

    try:
        r    = requests.get(search_url, headers=HEADERS, timeout=10)
        html = r.text

        video_ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)

        seen = set()
        for vid in video_ids:
            if vid in seen:
                continue
            seen.add(vid)

            if f'/shorts/{vid}' in html:
                continue
            return f"https://www.youtube.com/watch?v={vid}"

    except Exception as e:
        print(f"[YouTube] ⚠️ scrape_first_video_url failed: {e}")

    return None

def _extract_video_id(url: str) -> str | None:
    match = re.search(
        r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([A-Za-z0-9_-]{11})", url
    )
    return match.group(1) if match else None


def _is_valid_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url or ""))


def _ask_for_url(prompt_text: str = "YouTube video URL:") -> str | None:
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()

        url = simpledialog.askstring("J.A.R.V.I.S", prompt_text, parent=root)
        return url.strip() if url else None
    except Exception as e:
        print(f"[YouTube] ⚠️ URL dialog failed: {e}")
        return None


def _get_transcript(video_id: str) -> str | None:
    if not _TRANSCRIPT_OK:
        return None
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript      = None

        lang_priority = ["en", "tr", "de", "fr", "es", "it", "pt", "ru", "ja", "ko", "ar", "zh"]

        try:
            transcript = transcript_list.find_manually_created_transcript(lang_priority)
        except Exception:
            pass

        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(lang_priority)
            except Exception:
                for t in transcript_list:
                    transcript = t
                    break

        if transcript is None:
            return None

        fetched = transcript.fetch()
        return " ".join(entry["text"] for entry in fetched)

    except Exception as e:
        print(f"[YouTube] ⚠️ Transcript fetch failed: {e}")
        return None


def _summarize_with_gemini(transcript: str, video_url: str) -> str:
    from google import genai as _genai
    from google.genai import types

    _client = _genai.Client(api_key=_get_api_key())
    max_chars = 80000
    truncated = transcript[:max_chars] + ("..." if len(transcript) > max_chars else "")
    response  = _client.models.generate_content(
        model="gemini-flash-latest",
        contents=f"Please summarize this YouTube video transcript:\n\n{truncated}",
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are JARVIS, an AI assistant. "
                "Summarize YouTube video transcripts clearly and concisely. "
                "Structure: 1-sentence overview, then 3-5 key points. "
                "Be direct. Address the user as 'sir'. "
                "Match the language of the transcript."
            )
        )
    )
    return response.text.strip()


def _save_summary(content: str, video_url: str) -> str:
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"youtube_summary_{ts}.txt"
    desktop  = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    filepath = desktop / filename

    header = (
        f"JARVIS — YouTube Summary\n"
        f"{'─' * 50}\n"
        f"URL    : {video_url}\n"
        f"Date   : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'─' * 50}\n\n"
    )
    filepath.write_text(header + content, encoding="utf-8")

    try:
        if is_windows():
            subprocess.Popen(["notepad.exe", str(filepath)])
        elif is_mac():
            subprocess.Popen(["open", "-t", str(filepath)])
        else:
            subprocess.Popen(["xdg-open", str(filepath)])
    except Exception as e:
        print(f"[YouTube] ⚠️ Could not open text editor: {e}")

    return str(filepath)


def _scrape_video_info(video_id: str) -> dict:
    if not _REQUESTS_OK:
        return {}
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text
        info = {}

        for key, pattern in [
            ("title",    r'"title":\{"runs":\[\{"text":"([^"]+)"'),
            ("channel",  r'"ownerChannelName":"([^"]+)"'),
            ("views",    r'"viewCount":"(\d+)"'),
            ("duration", r'"lengthSeconds":"(\d+)"'),
            ("likes",    r'"label":"([0-9,]+ likes)"'),
        ]:
            match = re.search(pattern, html)
            if match:
                raw = match.group(1)
                if key == "views":
                    info[key] = f"{int(raw):,}"
                elif key == "duration":
                    secs = int(raw)
                    info[key] = f"{secs // 60}:{secs % 60:02d}"
                else:
                    info[key] = raw

        return info
    except Exception as e:
        print(f"[YouTube] ⚠️ Info scrape failed: {e}")
        return {}


def _scrape_trending(region: str = "TR", max_results: int = 8) -> list[dict]:
    if not _REQUESTS_OK:
        return []
    url = f"https://www.youtube.com/feed/trending?gl={region.upper()}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text

        titles   = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', html)
        channels = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', html)

        results, seen = [], set()
        for i, title in enumerate(titles):
            if title in seen or len(title) < 5:
                continue
            seen.add(title)
            channel = channels[i] if i < len(channels) else "Unknown"
            results.append({"rank": len(results) + 1, "title": title, "channel": channel})
            if len(results) >= max_results:
                break

        return results
    except Exception as e:
        print(f"[YouTube] ⚠️ Trending scrape failed: {e}")
        return []

def _handle_play(parameters: dict, player) -> str:
    query = parameters.get("query", "").strip()
    if not query:
        return "Ji, bataiye kya dekhna hai."

    if player:
        player.write_log(f"[YouTube] Searching: {query}")

    print(f"[YouTube] 🔍 Scraping first non-Shorts video for: {query}")

    video_url = _scrape_first_video_url(query)

    if video_url:
        print(f"[YouTube] ▶️ Opening: {video_url}")
        _open_in_chrome(video_url)
        return f"Playing: {query}"

    print(f"[YouTube] ⚠️ Scrape failed, opening filtered search page")
    fallback_url = (
        f"https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}"
        f"&sp={_YT_VIDEO_FILTER}"
    )
    _open_in_chrome(fallback_url)
    return f"Opened YouTube search for: {query} (manual selection required)"


def _open_in_chrome(url: str) -> None:
    """Open a YouTube URL in Google Chrome, reusing the user's real Chrome profile."""
    try:
        from actions.browser_control import browser_control
        browser_control(
            parameters={"action": "go_to", "url": url, "browser": "chrome"},
            player=None,
        )
    except Exception as e:
        print(f"[YouTube] ⚠️ chrome_common open failed ({e}), falling back to default opener")
        _open_url(url)


def _handle_summarize(parameters: dict, player, speak) -> str:
    if not _TRANSCRIPT_OK:
        return "youtube-transcript-api is not installed. Run: pip install youtube-transcript-api"

    url = _ask_for_url("Please paste the YouTube video URL:")
    if not url:
        return "No URL provided, sir. Summary cancelled."
    if not _is_valid_youtube_url(url):
        return "That doesn't appear to be a valid YouTube URL, sir."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID from that URL, sir."

    if player:
        player.write_log(f"[YouTube] Summarizing: {url}")
    if speak:
        speak("Fetching the transcript now, sir. One moment.")

    transcript = _get_transcript(video_id)
    if not transcript:
        return "I couldn't retrieve a transcript for that video, sir."

    if speak:
        speak("Transcript retrieved. Generating summary now.")

    try:
        summary = _summarize_with_gemini(transcript, url)
    except Exception as e:
        return f"Summary generation failed, sir: {e}"

    if speak:
        speak(summary)

    if parameters.get("save", False):
        saved_path = _save_summary(summary, url)
        return f"Summary complete and saved to Desktop: {saved_path}"

    return summary


def _handle_get_info(parameters: dict, player, speak) -> str:
    url = parameters.get("url", "").strip()
    if not url:
        url = _ask_for_url("Please paste the YouTube video URL:")
    if not url or not _is_valid_youtube_url(url):
        return "Please provide a valid YouTube URL, sir."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID, sir."

    if player:
        player.write_log(f"[YouTube] Getting info: {url}")

    info = _scrape_video_info(video_id)
    if not info:
        return "Could not retrieve video information, sir."

    lines = [
        f"{key.capitalize()}: {info[key]}"
        for key in ("title", "channel", "views", "duration", "likes")
        if key in info
    ]
    result = "\n".join(lines)

    if speak:
        speak(f"Here's the video info, sir. {result.replace(chr(10), '. ')}")

    return result


def _handle_trending(parameters: dict, player, speak) -> str:
    region = parameters.get("region", "TR").upper()

    if player:
        player.write_log(f"[YouTube] Trending: {region}")

    trending = _scrape_trending(region=region, max_results=8)
    if not trending:
        return f"Could not fetch trending videos for region {region}, sir."

    lines  = [f"Top trending videos in {region}:"]
    lines += [f"{v['rank']}. {v['title']} — {v['channel']}" for v in trending]
    result = "\n".join(lines)

    if speak:
        top3   = trending[:3]
        spoken = "Here are the top trending videos, sir. " + ". ".join(
            f"Number {v['rank']}: {v['title']} by {v['channel']}" for v in top3
        )
        speak(spoken)

    return result

def _handle_search(parameters: dict, player) -> str:
    """Open a YouTube search results page in Google Chrome."""
    query = parameters.get("query", "").strip() or parameters.get("text", "").strip()
    if not query:
        return "Ji, kya search karna hai? Bataiye."
    search_url = (
        f"https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}"
    )
    if player:
        player.write_log(f"[YouTube] Searching: {query}")
    _open_in_chrome(search_url)
    return f"Opened YouTube search for: {query}"


# ── Injected JS helpers (read+write the REAL YouTube player DOM) ──────────

_JS_VIDEO = r"""
(function () {
  var v = document.querySelector('video');
  if (!v) return 'NO_VIDEO';
  var paused = v.paused;
  var t = v.currentTime || 0;
  var d = v.duration || 0;
  var m = String(t).replace(/:(?=\d\d\d)/, '');
  function fmt(s){s=Math.floor(s);var h=Math.floor(s/3600);var mm=Math.floor((s%3600)/60);var ss=s%60;return (h?h+':':'')+(mm<10&&h?'0':'')+mm+':'+(ss<10?'0':'')+ss;}
  return 'PAUSED=' + (paused ? 'true' : 'false') + '|TIME=' + fmt(t) + '|DUR=' + fmt(d) + '|URL=' + location.href;
})();
"""

_JS_PLAY = r"var v=document.querySelector('video'); if(!v){'NO_VIDEO';}else{v.play(); 'OK';}"
_JS_PAUSE = r"var v=document.querySelector('video'); if(!v){'NO_VIDEO';}else{v.pause(); 'OK';}"

_JS_MUTE = r"""
var v=document.querySelector('video'); if(!v){'NO_VIDEO';}else{v.muted=true; v.volume=0; 'OK';}
"""
_JS_UNMUTE = r"""
var v=document.querySelector('video'); if(!v){'NO_VIDEO';}else{v.muted=false; if(v.volume===0){v.volume=1;} 'OK';}
"""

_JS_VOL_UP = r"""
var v=document.querySelector('video'); if(!v){'NO_VIDEO';}else{v.muted=false; v.volume=Math.min(1, v.volume+0.1); 'OK';}
"""
_JS_VOL_DOWN = r"""
var v=document.querySelector('video'); if(!v){'NO_VIDEO';}else{v.volume=Math.max(0, v.volume-0.1); if(v.volume===0){v.muted=true;} 'OK';}
"""

_JS_FULLSCREEN = r"""
(function(){
 var p=document.querySelector('video');
 if(!p){return 'NO_VIDEO';}
 if (document.fullscreenElement){ document.exitFullscreen(); return 'exited'; }
 if (p.requestFullscreen){ p.requestFullscreen(); return 'entered'; }
 return 'unsupported';
})();
"""

_JS_NEXT = r"""
(function(){
 var btn=document.querySelector('.ytp-next-button');
 if(btn){btn.click(); return 'OK';}
 return 'NO_BTN';
})();
"""

_JS_PREV = r"""
(function(){
 var btn=document.querySelector('.ytp-prev-button');
 if(btn){btn.click(); return 'OK';}
 return 'NO_BTN';
})();
"""

_JS_SEEK = r"""
(function(sec){
 var v=document.querySelector('video'); if(!v){return 'NO_VIDEO';}
 var d=v.duration||0;
 if(sec<0){sec=0;} if(sec>d){sec=d;}
 v.currentTime=sec; return 'OK';
})
"""

_JS_COMMENTS = r"""
(function(){
 var btn=document.querySelector('[aria-label*=comments i]')||document.querySelector('.ytd-comments-header-renderer');
 if(btn){btn.scrollIntoView({behavior:'smooth',block:'center'}); return 'OK';}
 return 'NO_BTN';
})();
"""


def _control_dispatch(sub: str, value) -> str:
    """Map a control sub-action to {js, label, expected} or None if unknown."""
    js_map = {
        "play":         (_JS_PLAY,         "play"),
        "toggle":       (_JS_PLAY,         "play"),   # toggle handled separately
        "pause":        (_JS_PAUSE,        "pause"),
        "next":         (_JS_NEXT,         "next"),
        "previous":     (_JS_PREV,         "previous"),
        "volume_up":    (_JS_VOL_UP,       "volume_up"),
        "volume_down":  (_JS_VOL_DOWN,     "volume_down"),
        "mute":         (_JS_MUTE,         "mute"),
        "unmute":       (_JS_UNMUTE,       "unmute"),
        "fullscreen":   (_JS_FULLSCREEN,   "fullscreen"),
        "comments":     (_JS_COMMENTS,     "comments"),
    }
    if sub in js_map:
        return js_map[sub]
    if sub in ("get_state",):
        return ("'get_state'", "get_state")
    if sub in ("exit_fullscreen", "fullscreen_exit"):
        return (_JS_FULLSCREEN, "exit_fullscreen")
    if sub == "set_volume":
        try:
            val = max(0.0, min(1.0, float(value) / 100.0 if value and float(value) > 1 else float(value or 0)))
        except Exception:
            val = 0.5
        return (f"var v=document.querySelector('video'); if(!v){{'NO_VIDEO';}}else{{v.muted=false; v.volume={val}; 'OK';}}", "set_volume")
    if sub == "seek":
        try:
            sec = int(float(value or 0))
        except Exception:
            sec = 0
        return (f"{_JS_SEEK}({sec})", "seek")
    return None


def _handle_control(parameters: dict, player, speak) -> str:
    """Real YouTube player control with PRE/ACTION/POST verification."""
    from actions.browser_control import browser_control as _bc

    sub = parameters.get("sub_action", "").lower().strip()
    value = parameters.get("value", 0)
    if not sub:
        return "Ji, bataiye kya karna hai (pause, play, volume, fullscreen, seek…)."

    tgt = _control_dispatch(sub, value)
    if tgt is None:
        return (f"Unknown control: '{sub}'. Options: pause, play, toggle, mute, unmute, "
                "volume_up, volume_down, set_volume, fullscreen, exit_fullscreen, next, "
                "previous, seek, stop, comments, get_state.")

    try:
        state = _bc(parameters={"action": "get_active_page_state", "browser": "chrome"}, player=None)
    except Exception as e:
        return f"Ji, Chrome ke tab ki state check nahi ho saki: {e}"

    if "youtube.com" not in state and "youtu.be" not in state:
        return ("YouTube open nahi hai ya Chrome ka control tab sahi nahi mil raha. "
                "Pehle YouTube kholiye, phir main control kar sakta hoon.")
    if "watch" not in state and sub not in ("get_state", "comments", "search"):
        return "Ji, abhi koi video page open nahi hai — pehle koi video play karaiye."

    # PRE-CHECK — read the current real player state
    pre = _bc(parameters={"action": "eval_js", "browser": "chrome", "script": _JS_VIDEO}, player=None)
    if isinstance(pre, str) and pre.startswith("NO_VIDEO"):
        return "Video player nahi mila — kya yakeen hai ke video open hai? Main confirm nahi kar saka."

    # ACTION
    js, label = tgt
    out = _bc(parameters={"action": "eval_js", "browser": "chrome", "script": js}, player=None)
    if isinstance(out, str) and out.startswith(("NO_VIDEO", "NO_BTN", "JS_ERROR")):
        return f"Ji, {label} command bheji, lekin player ne respond nahi kiya ({out}). Main claim nahi karunga."

    if sub == "toggle":
        if "PAUSED=true" in (pre or ""):
            _bc(parameters={"action": "eval_js", "browser": "chrome", "script": _JS_PLAY}, player=None)
            sub = "play"
        else:
            _bc(parameters={"action": "eval_js", "browser": "chrome", "script": _JS_PAUSE}, player=None)
            sub = "pause"

    if sub == "stop":
        _bc(parameters={"action": "eval_js", "browser": "chrome",
                        "script": f"{_JS_SEEK}(0)"}, player=None)
        _bc(parameters={"action": "eval_js", "browser": "chrome", "script": _JS_PAUSE}, player=None)

    # POST-CHECK — verify the state actually changed
    post = _bc(parameters={"action": "eval_js", "browser": "chrome", "script": _JS_VIDEO}, player=None)
    if isinstance(post, str) and post.startswith("NO_VIDEO"):
        return "Ji, post-check me video player nahi mila — result verify nahi ho saka."

    def _paused_flag(s):
        return "PAUSED=true" in (s or "")

    if sub in ("pause", "play", "toggle", "stop"):
        ok = ("PLAYING" if sub == "play" and not _paused_flag(post) else
              "PAUSED" if sub in ("pause", "stop") and _paused_flag(post) else
              "CHANGED" if sub == "toggle" else "UNKNOWN")
        status = {
            "play": "video ab play ho rahi hai" if ok == "PLAYING" else "play verify nahi ho saki",
            "pause": "video pause ho gayi hai" if ok == "PAUSED" else "pause verify nahi ho saka",
            "stop": "video ruk gayi hai" if ok == "PAUSED" else "stop verify nahi ho saka",
            "toggle": "state badal gayi hai" if ok == "CHANGED" else "toggle verify nahi ho saka",
        }[sub]
        return f"{status}."
    if sub == "set_volume" or sub == "volume_up" or sub == "volume_down" or sub == "mute" or sub == "unmute":
        vol = "confirm nahi ho saka"
        try:
            vres = _bc(parameters={"action": "eval_js", "browser": "chrome",
                                   "script": r"var v=document.querySelector('video'); v ? (Math.round((v.volume||0)*100)+'%') : 'NO_VIDEO';"}, player=None)
            if vres and vres != "NO_VIDEO":
                vol = vres
        except Exception:
            pass
        if sub == "mute":
            return f"Volume mute kar diya (verified: {vol})."
        if sub == "unmute":
            return f"Volume wapas on kar diya (verified: {vol})."
        return f"Volume adjust ho gaya (verified: {vol})."
    if sub in ("fullscreen",):
        return "Fullscreen toggled kar diya — screen check kar sakte hain agar zaroorat ho."
    if sub in ("exit_fullscreen", "fullscreen_exit"):
        return "Fullscreen band kar diya."
    if sub == "next":
        return "Next video par chala gaya — verify ke liye screen check kar sakta hoon."
    if sub == "previous":
        return "Previous video par chala gaya."
    if sub == "seek":
        mins = value
        try:
            sec = int(float(value or 0))
            mins = round(sec / 60, 1)
        except Exception:
            pass
        return f"Video ko {mins} minute par le gaya."
    if sub == "comments":
        return "Comments section scroll kar diya."
    if sub == "get_state":
        return f"Player state: {post}"

    return f"{label} command bheji — result: {post}"


_ACTION_MAP = {
    "play":      _handle_play,
    "summarize": _handle_summarize,
    "get_info":  _handle_get_info,
    "trending":  _handle_trending,
    "search":    _handle_search,
    "control":   _handle_control,
}


def youtube_video(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "play").lower().strip()

    if player:
        player.write_log(f"[YouTube] Action: {action}")
    print(f"[YouTube] ▶️  Action: {action}  Params: {params}")

    handler = _ACTION_MAP.get(action)
    if handler is None:
        return (
            f"Unknown YouTube action: '{action}'. "
            "Available: play, search, control, summarize, get_info, trending."
        )

    try:
        if action in ("play", "search"):
            return handler(params, player) or "Done."
        if action == "control":
            return handler(params, player, speak) or "Done."
        return handler(params, player, speak) or "Done."
    except Exception as e:
        print(f"[YouTube] ❌ Error in {action}: {e}")
        return f"YouTube {action} failed: {e}"