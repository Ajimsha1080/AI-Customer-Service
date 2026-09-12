import os
import pytest

def test_widget_file_exists():
    widget_public_path = os.path.join("apps", "web", "public", "widget.js")
    widget_source_path = os.path.join("apps", "widget", "widget.js")
    
    assert os.path.exists(widget_public_path), "widget.js must exist in apps/web/public/ for embed serving"
    assert os.path.exists(widget_source_path), "widget.js must exist in apps/widget/ source directory"

    with open(widget_public_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    assert "Hospitality Agent Cloud" in content or "Widget" in content

