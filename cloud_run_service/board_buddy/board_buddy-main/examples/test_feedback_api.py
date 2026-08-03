import os
import sys
import json
from board_buddy import BoardBuddyCanvas

def main():
    print("==================================================")
    print("[TEST SUITE] BOARD BUDDY DIAGNOSTIC FEEDBACK API")
    print("==================================================")

    canvas = BoardBuddyCanvas(width=600, height=800, theme="whiteboard")

    # TEST 1: Clean Valid Payload
    valid_payload = [
        {
            "id": "t1_header",
            "type": "text",
            "pos": [30, 20],
            "text": "Valid Payload Test",
            "size": "large"
        },
        {
            "id": "t1_apple",
            "type": "stickers",
            "pos": [30, 80],
            "name": "apple",
            "count": 3
        }
    ]

    res1 = canvas.load_json(valid_payload)
    print("\n[TEST 1] Valid Payload Response:")
    print(json.dumps(res1, indent=2))
    assert res1["status"] == "success"
    assert res1["loaded_count"] == 2

    # TEST 2: Malformed JSON String Input
    malformed_json_str = "[{'id': 'bad_json', 'type': 'text'}"  # Invalid JSON quotes/brackets
    res2 = canvas.load_json(malformed_json_str)
    print("\n[TEST 2] Malformed JSON String Response:")
    print(json.dumps(res2, indent=2))
    assert res2["status"] == "error"
    assert len(res2["errors"]) > 0

    # TEST 3: Partial Payload with Unknown Element Type & Missing Fields
    partial_payload = [
        {
            "id": "t3_valid",
            "type": "text",
            "pos": [30, 150],
            "text": "Partial Test Valid Item"
        },
        {
            "id": "t3_unknown",
            "type": "non_existent_tool_type",  # Unknown tool type
            "pos": [30, 200]
        },
        {
            "type": "stickers"  # Missing required 'id' field
        }
    ]

    res3 = canvas.load_json(partial_payload)
    print("\n[TEST 3] Partial Payload Response:")
    print(json.dumps(res3, indent=2))
    assert res3["status"] == "partial_success"
    assert res3["loaded_count"] == 2
    assert len(res3["warnings"]) == 2

    # TEST 4: Render Test with Non-Intrusive Fault Isolation
    try:
        img = canvas.render()
        print(f"\n[TEST 4] Render pass completed cleanly! Generated PIL image dimensions: {img.size}")
    except Exception as e:
        print(f"\n[TEST 4 FAILED] Render crash encountered: {e}")
        sys.exit(1)

    print("\n[SUCCESS] ALL DIAGNOSTIC FEEDBACK API TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
