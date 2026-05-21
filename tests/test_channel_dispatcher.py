from __future__ import annotations

from channels.channel_dispatcher import _format_channel_message


def test_format_channel_message_converts_escaped_newlines():
    message = _format_channel_message(
        "",
        "Perfect.\\n\\nQuick reality check: What is your budget?",
    )

    assert "\\n" not in message
    assert message == "Perfect.\n\nQuick reality check: What is your budget?"


def test_format_channel_message_converts_subject_and_body():
    message = _format_channel_message(
        "Re: Lead\\nFollow-up",
        "Hi there\\n\\nThanks.",
    )

    assert message == "Subject: Re: Lead\nFollow-up\n\nHi there\n\nThanks."
