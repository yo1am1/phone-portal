"""Schemas for the Hermes iOS phone plugin."""

IOS_PHONE_BEGIN_UPLOAD = {
    "name": "ios_phone_begin_upload",
    "description": (
        "Start the smartphone upload flow in one step. Returns the exact http:// link, QR path, "
        "short instructions, and current file baseline so Hermes can wait for new files."
    ),
    "parameters": {"type": "object", "properties": {}},
}

IOS_PHONE_LINK = {
    "name": "ios_phone_link",
    "description": (
        "Get the exact http:// link for the current phone-upload page so the user can open it on iPhone/iPad. "
        "Prefer ios_phone_begin_upload for the normal first step because it also returns the baseline needed to wait for only new uploads."
    ),
    "parameters": {"type": "object", "properties": {}},
}

IOS_PHONE_WAIT_FOR_FILES = {
    "name": "ios_phone_wait_for_files",
    "description": (
        "Wait for new files to appear from the phone upload page, then return the current uploaded file list. "
        "Pass since_count or since_uploaded_at from ios_phone_begin_upload to avoid returning old files."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "timeout_seconds": {
                "type": "integer",
                "description": "How long to wait. Default 120 seconds.",
            },
            "poll_interval_seconds": {
                "type": "integer",
                "description": "Polling interval. Default 2 seconds.",
            },
            "min_files": {
                "type": "integer",
                "description": "Minimum number of new uploaded files required before returning. Default 1.",
            },
            "since_count": {
                "type": "integer",
                "description": "Existing file count baseline. Usually from ios_phone_begin_upload.",
            },
            "since_uploaded_at": {
                "type": "number",
                "description": "Timestamp baseline. Usually latest_uploaded_at from ios_phone_begin_upload.",
            }
        },
    },
}

IOS_PHONE_READ_LATEST_FILE = {
    "name": "ios_phone_read_latest_file",
    "description": (
        "Read the most recently uploaded phone file without asking for a file_id. "
        "Use this when the user uploaded one obvious file and wants you to use it immediately."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "max_bytes": {
                "type": "integer",
                "description": "Maximum bytes to read; default 200000.",
            }
        },
    },
}

IOS_PHONE_STATUS = {
    "name": "ios_phone_status",
    "description": "Check whether the local Hermes iPhone/iPad web bridge has a remembered or active Safari companion session.",
    "parameters": {"type": "object", "properties": {}},
}

IOS_PHONE_LIST_FILES = {
    "name": "ios_phone_list_files",
    "description": (
        "List files explicitly selected by the user in the paired iPhone/iPad web companion. "
        "Use this before reading a specific file by id, or when multiple files were uploaded."
    ),
    "parameters": {"type": "object", "properties": {}},
}

IOS_PHONE_READ_FILE = {
    "name": "ios_phone_read_file",
    "description": (
        "Read a user-selected file from the paired iPhone/iPad session by file id. "
        "The file id comes from ios_phone_list_files. Returns UTF-8 text when possible, "
        "otherwise returns base64 with metadata."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "File identifier returned by ios_phone_list_files.",
            },
            "max_bytes": {
                "type": "integer",
                "description": "Maximum bytes to read; default 200000, upper limit enforced by bridge.",
            }
        },
        "required": ["file_id"],
    },
}


IOS_PHONE_SUMMARY = {
    "name": "ios_phone_summary",
    "description": "Return a human-friendly summary of the phone bridge status, latest file, and suggested next tool call.",
    "parameters": {"type": "object", "properties": {}},
}

IOS_PHONE_CREATE_ZIP = {
    "name": "ios_phone_create_zip",
    "description": "Create a zip bundle from all currently uploaded files.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Optional zip filename (defaults to bundle-<timestamp>.zip).",
            }
        },
    },
}

IOS_PHONE_SEND_TEXT = {
    "name": "ios_phone_send_text",
    "description": "Send a text message from the agent to the phone display. The phone will show it in a 'From Agent' section.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Message body to display on the phone."},
            "title": {"type": "string", "description": "Optional message title."},
        },
        "required": ["text"],
    },
}

IOS_PHONE_DELETE_FILE = {
    "name": "ios_phone_delete_file",
    "description": "Delete an uploaded file by id. Use after reading a file to free up space.",
    "parameters": {
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "File id from ios_phone_list_files."},
        },
        "required": ["file_id"],
    },
}
