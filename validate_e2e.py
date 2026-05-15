#!/usr/bin/env python3
"""End-to-end validation of the phone-link MCP plugin."""

from __future__ import annotations

import json
import sys
import traceback

# Ensure the project paths are on sys.path
sys.path.insert(0, '/home/user/VS/foo/hermes-phone-link')
sys.path.insert(0, '/home/user/VS/foo/hermes-phone-link/mcp')

results: list[tuple[str, str, str]] = []  # (step, status, detail)


def record(step: str, passed: bool, detail: str) -> None:
    status = "PASS" if passed else "FAIL"
    results.append((step, status, detail))
    marker = "✓" if passed else "✗"
    print(f"  [{marker}] {step}: {status}")
    print(f"       {detail}")
    print()


# ---------------------------------------------------------------------------
# Step 1 — Import and start bridge
# ---------------------------------------------------------------------------
print("=" * 70)
print("STEP 1: Import phone_link_server and start bridge")
print("=" * 70)
try:
    import phone_link_server as srv  # noqa: E402 — intentional late import
    srv._ensure_bridge()
    record("Step 1 - Import & bridge start", True, "_ensure_bridge() completed without exception")
except Exception as exc:
    record("Step 1 - Import & bridge start", False, f"Exception: {exc}")
    traceback.print_exc()

# ---------------------------------------------------------------------------
# Step 2 — ios_phone_begin_upload
# ---------------------------------------------------------------------------
print("=" * 70)
print("STEP 2: ios_phone_begin_upload")
print("=" * 70)
try:
    raw2 = srv.ios_phone_begin_upload()
    print(f"  raw return (truncated to 500):\n{raw2[:500]}")
    print()
    # begin_upload returns a formatted string, not JSON — parse the JSON embedded at call time
    # Actually it returns a formatted multi-line string. Let's check the underlying tool directly.
    from plugin.ios_phone import tools as _tools
    data2 = json.loads(_tools.ios_phone_begin_upload({}))
    ok2 = data2.get("ok") is True
    url2 = data2.get("url", "")
    qr2 = data2.get("qr_ascii", "")
    efc2 = "existing_file_count" in data2
    lua2 = "latest_uploaded_at" in data2
    all_ok2 = ok2 and bool(url2) and len(qr2) > 50 and efc2 and lua2
    record(
        "Step 2 - ios_phone_begin_upload",
        all_ok2,
        f"ok={ok2}, url={url2[:60]!r}, qr_ascii_len={len(qr2)}, "
        f"existing_file_count_present={efc2}, latest_uploaded_at_present={lua2}",
    )
    # Save baseline for later steps
    existing_file_count = data2.get("existing_file_count", 0)
    latest_uploaded_at = data2.get("latest_uploaded_at", 0.0)
    upload_url = url2
except Exception as exc:
    record("Step 2 - ios_phone_begin_upload", False, f"Exception: {exc}")
    traceback.print_exc()
    existing_file_count = 0
    latest_uploaded_at = 0.0
    upload_url = ""

# ---------------------------------------------------------------------------
# Step 3 — ios_phone_status
# ---------------------------------------------------------------------------
print("=" * 70)
print("STEP 3: ios_phone_status")
print("=" * 70)
try:
    raw3 = srv.ios_phone_status()
    data3 = json.loads(raw3)
    ok3 = data3.get("ok") is True
    connected_present3 = "connected" in data3
    record(
        "Step 3 - ios_phone_status",
        ok3 and connected_present3,
        f"ok={ok3}, connected_present={connected_present3}, connected={data3.get('connected')}",
    )
except Exception as exc:
    record("Step 3 - ios_phone_status", False, f"Exception: {exc}")
    traceback.print_exc()

# ---------------------------------------------------------------------------
# Step 4 — ios_phone_list_files
# ---------------------------------------------------------------------------
print("=" * 70)
print("STEP 4: ios_phone_list_files")
print("=" * 70)
files_for_step5: list[dict] = []
try:
    raw4 = srv.ios_phone_list_files()
    data4 = json.loads(raw4)
    ok4 = data4.get("ok") is True
    files_present4 = "files" in data4
    files_for_step5 = data4.get("files") or []
    record(
        "Step 4 - ios_phone_list_files",
        ok4 and files_present4,
        f"ok={ok4}, files_present={files_present4}, file_count={len(files_for_step5)}",
    )
except Exception as exc:
    record("Step 4 - ios_phone_list_files", False, f"Exception: {exc}")
    traceback.print_exc()

# ---------------------------------------------------------------------------
# Step 5 — ios_phone_read_file (if files exist)
# ---------------------------------------------------------------------------
print("=" * 70)
print("STEP 5: ios_phone_read_file")
print("=" * 70)
if files_for_step5:
    first_file = files_for_step5[0]
    file_id5 = first_file.get("id", "")
    try:
        raw5 = srv.ios_phone_read_file(file_id=file_id5)
        data5 = json.loads(raw5)
        ok5 = data5.get("ok") is True
        id_present5 = "id" in data5
        result_absent5 = "result" not in data5  # should be unwrapped
        record(
            "Step 5 - ios_phone_read_file",
            ok5 and id_present5 and result_absent5,
            f"ok={ok5}, id_in_response={id_present5}, result_NOT_in_response={result_absent5}, keys={list(data5.keys())}",
        )
    except Exception as exc:
        record("Step 5 - ios_phone_read_file", False, f"Exception: {exc}")
        traceback.print_exc()
else:
    record("Step 5 - ios_phone_read_file", True, "SKIPPED — no files present (no files to read, step skipped per spec)")

# ---------------------------------------------------------------------------
# Step 6 — ios_phone_read_latest_file
# ---------------------------------------------------------------------------
print("=" * 70)
print("STEP 6: ios_phone_read_latest_file")
print("=" * 70)
try:
    raw6 = srv.ios_phone_read_latest_file()
    data6 = json.loads(raw6)
    ok6 = data6.get("ok") is True
    selected_present6 = "selected_file" in data6
    # If no files exist, ok will be False with a clear error — acceptable skip
    if not files_for_step5:
        # Expecting ok=False and error about no files
        no_files_error6 = "no uploaded files" in str(data6.get("error", ""))
        record(
            "Step 6 - ios_phone_read_latest_file",
            not ok6 and no_files_error6,
            f"No files — ok={ok6}, error={data6.get('error')!r} (expected 'no uploaded files')",
        )
    else:
        record(
            "Step 6 - ios_phone_read_latest_file",
            ok6 and selected_present6,
            f"ok={ok6}, selected_file_present={selected_present6}",
        )
except Exception as exc:
    record("Step 6 - ios_phone_read_latest_file", False, f"Exception: {exc}")
    traceback.print_exc()

# ---------------------------------------------------------------------------
# Step 7 — ios_phone_create_zip
# ---------------------------------------------------------------------------
print("=" * 70)
print("STEP 7: ios_phone_create_zip")
print("=" * 70)
try:
    raw7 = srv.ios_phone_create_zip()
    data7 = json.loads(raw7)
    if not files_for_step5:
        # Bridge returns ok=False because there are no files to zip
        no_files_error7 = not data7.get("ok")
        record(
            "Step 7 - ios_phone_create_zip",
            no_files_error7,
            f"No files — ok={data7.get('ok')}, error={data7.get('error')!r} (expected failure — no files)",
        )
    else:
        ok7 = data7.get("ok") is True
        file_id_present7 = isinstance(data7.get("file"), dict) and "id" in data7["file"]
        record(
            "Step 7 - ios_phone_create_zip",
            ok7 and file_id_present7,
            f"ok={ok7}, file.id_present={file_id_present7}, file={data7.get('file')}",
        )
except Exception as exc:
    record("Step 7 - ios_phone_create_zip", False, f"Exception: {exc}")
    traceback.print_exc()

# ---------------------------------------------------------------------------
# Step 8 — ios_phone_summary
# ---------------------------------------------------------------------------
print("=" * 70)
print("STEP 8: ios_phone_summary")
print("=" * 70)
try:
    raw8 = srv.ios_phone_summary()
    data8 = json.loads(raw8)
    ok8 = data8.get("ok") is True
    suggested_present8 = "suggested_next" in data8
    record(
        "Step 8 - ios_phone_summary",
        ok8 and suggested_present8,
        f"ok={ok8}, suggested_next_present={suggested_present8}, suggested_next={data8.get('suggested_next')!r}",
    )
except Exception as exc:
    record("Step 8 - ios_phone_summary", False, f"Exception: {exc}")
    traceback.print_exc()

# ---------------------------------------------------------------------------
# Step 9 — ios_phone_wait_for_files with timeout (expected FAIL/timeout)
# ---------------------------------------------------------------------------
print("=" * 70)
print("STEP 9: ios_phone_wait_for_files timeout=3, since_count=9999 (expect timeout error)")
print("=" * 70)
try:
    raw9 = srv.ios_phone_wait_for_files(timeout_seconds=3, since_count=9999)
    data9 = json.loads(raw9)
    ok9 = data9.get("ok")
    error9 = data9.get("error", "")
    timed_out9 = ok9 is False and "timeout" in error9.lower()
    record(
        "Step 9 - ios_phone_wait_for_files timeout",
        timed_out9,
        f"ok={ok9}, error={error9!r} (expected ok=False with timeout message)",
    )
except Exception as exc:
    record("Step 9 - ios_phone_wait_for_files timeout", False, f"Exception: {exc}")
    traceback.print_exc()

# ---------------------------------------------------------------------------
# Step 10 — Cleanup
# ---------------------------------------------------------------------------
print("=" * 70)
print("STEP 10: Cleanup")
print("=" * 70)
try:
    srv._cleanup()
    record("Step 10 - Cleanup", True, "_cleanup() called successfully")
except Exception as exc:
    record("Step 10 - Cleanup", False, f"Exception: {exc}")
    traceback.print_exc()

# ---------------------------------------------------------------------------
# Summary Table
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("SUMMARY TABLE")
print("=" * 70)
print(f"{'Step':<45} {'Status':<6}")
print("-" * 70)
passed = 0
failed = 0
for step, status, _detail in results:
    print(f"{step:<45} {status:<6}")
    if status == "PASS":
        passed += 1
    else:
        failed += 1
print("-" * 70)
print(f"  PASSED: {passed}   FAILED: {failed}   TOTAL: {passed + failed}")
print("=" * 70)

sys.exit(0 if failed == 0 else 1)
