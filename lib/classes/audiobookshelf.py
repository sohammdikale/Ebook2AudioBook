import os
import requests
from pathlib import Path


def fetch_libraries(server_url:str, api_token:str)->list[tuple[str, str]]:
    try:
        resp = requests.get(
            server_url.rstrip("/") + "/api/libraries",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=10,
        )
        if resp.ok:
            return [
                (lib["name"], lib["id"])
                for lib in resp.json().get("libraries", [])
                if lib.get("id")
            ]
        else:
            error = f"ABS library fetch failed ({resp.status_code}): {resp.text[:200]}"
            print(error)
            return []
    except Exception as e:
        error = f"ABS library fetch error: {type(e).__name__}: {e}"
        print(error)
        return []


MIME_MAP:dict = {
    ".m4b": "audio/mp4",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".opus": "audio/opus",
}


def _detect_folder_id(server_url:str, headers:dict, library_id:str)->str:
    try:
        lib_resp = requests.get(
            server_url.rstrip("/") + "/api/libraries",
            headers=headers,
            timeout=10,
        )
        if not lib_resp.ok:
            error = f"ABS folder auto-detect failed ({lib_resp.status_code}): {lib_resp.text[:200]}"
            print(error)
            return ""
        for lib in lib_resp.json().get("libraries", []):
            if lib.get("id") == library_id:
                folders = lib.get("folders", [])
                if folders:
                    return folders[0].get("id", "")
                error = f"ABS library {library_id} has no folders"
                print(error)
                return ""
        error = f"ABS library {library_id} not found on server"
        print(error)
    except Exception as e:
        error = f"ABS folder auto-detect failed: {type(e).__name__}: {e}"
        print(error)
    return ""


def upload_to_abs(
    file_path:str|list[str],
    title:str,
    author:str,
    server_url:str,
    api_token:str,
    library_id:str,
    folder_id:str = "",
    timeout:int = 1800,
)->tuple[bool, str]:
    if isinstance(file_path, str):
        file_path = [file_path]
    existing:list[str] = [f for f in file_path if os.path.isfile(f)]
    if not existing:
        msg = f"ABS upload skipped: no valid files in {file_path}"
        print(msg)
        return (False, 'No valid files to upload')
    if not library_id:
        msg = "ABS upload skipped: no library_id"
        print(msg)
        return (False, 'No library selected')
    url:str = server_url.rstrip("/") + "/api/upload"
    headers:dict = {"Authorization": f"Bearer {api_token}"}
    if not folder_id:
        folder_id = _detect_folder_id(server_url, headers, library_id)
    if not folder_id:
        msg = "ABS upload skipped: could not resolve folder id"
        print(msg)
        return (False, 'Could not resolve library folder')
    total_bytes:int = sum(os.path.getsize(f) for f in existing)
    form_data:dict = {
        "title": title or Path(existing[0]).stem,
        "library": library_id,
        "folder": folder_id,
    }
    if author:
        form_data["author"] = author
    files_dict:dict = {}
    handles:list = []
    try:
        for i, fp in enumerate(existing):
            fh = open(fp, "rb")
            handles.append(fh)
            mime_type:str = MIME_MAP.get(Path(fp).suffix.lower(), "audio/mp4")
            files_dict[str(i)] = (Path(fp).name, fh, mime_type)
        print(f"ABS upload: {len(existing)} file(s), {total_bytes / 1048576:.1f} MB -> {url}")
        resp = requests.post(
            url,
            headers=headers,
            files=files_dict,
            data=form_data,
            timeout=(30, timeout),
        )
        if resp.ok:
            names:str = ", ".join(Path(f).name for f in existing)
            msg = f"Uploaded to Audiobookshelf: {names}"
            print(msg)
            return (True, f'Uploaded: {names}')
        else:
            error = f"ABS upload failed ({resp.status_code}): {resp.text[:200]}"
            print(error)
            return (False, f'HTTP {resp.status_code}: {resp.text[:200]}')
    except requests.exceptions.ConnectTimeout as e:
        error = f"ABS upload failed: timed out connecting to {server_url}"
        print(error)
        return (False, f'Connect timeout to {server_url}')
    except requests.exceptions.ReadTimeout as e:
        error = f"ABS upload failed: no response after {timeout}s (upload may still be processing)"
        print(error)
        return (False, f'Read timeout after {timeout}s')
    except requests.exceptions.ConnectionError as e:
        # ConnectionError covers refused, reset, and broken pipe. The cause
        # matters: refused means nothing is listening, reset means the server
        # accepted the upload then dropped it (size limit, proxy, crash).
        cause = str(e)
        if 'Connection refused' in cause or 'NewConnectionError' in cause:
            hint = 'nothing listening - check host/port'
        elif 'reset' in cause.lower() or 'BrokenPipe' in cause or 'RemoteDisconnected' in cause:
            hint = 'server closed mid-upload - check body size limits and ABS logs'
        else:
            hint = 'connection error'
        error = f"ABS upload failed [{hint}]: {type(e).__name__}: {cause[:300]}"
        print(error)
        return (False, f'{hint}: {cause[:200]}')
    except Exception as e:
        error = f"ABS upload error: {type(e).__name__}: {e}"
        print(error)
        return (False, f'{type(e).__name__}: {e}')
    finally:
        for fh in handles:
            fh.close()
