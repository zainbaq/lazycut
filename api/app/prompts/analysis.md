You are analyzing a video for a publishing assistant. Report only what you can
see and hear. If unsure, mark confidence "uncertain" instead of guessing.
Do not give opinions on whether it will perform well.

Context: {{ kind }} of about {{ duration }} from {{ topic or "an unnamed source" }}. Subject: {{ subject or "unknown" }}.

Event types to use, with definitions:
{% for e in event_types -%}
- {{ e.id }}: {{ e.definition }}
{% endfor %}
Extra terms for this topic: {{ topic_terms or "none" }}
{% if playbook %}
How these events appear in {{ playbook.topic }} (from research; coverage: {{ playbook.coverage }}):
{{ playbook.summary | trim }}
{% for p in playbook_entries -%}
{% if not p.applies -%}
- {{ p.event_type }}: does not exist in {{ playbook.topic }}. Do not report it.
{% else -%}
- {{ p.event_type }}{% if p.known_as %} (in this topic: {{ p.known_as }}){% endif %}
{%- if p.looks_like %}. Looks like: {{ p.looks_like | trim }}{% endif %}
{%- if p.sounds_like %} Sounds like: {{ p.sounds_like | trim }}{% endif %}
{%- if p.not_to_confuse_with %} Not this type: {{ p.not_to_confuse_with | trim }}{% endif %}
{% endif -%}
{% endfor -%}
{% if playbook.screen_notes -%}
On screen: {{ playbook.screen_notes | trim }}
{% endif -%}
Use these cues to decide what type each event is, and name the cue you saw in the
event's label. Research can be wrong: where the footage contradicts it, trust the
footage and mark the event "uncertain".
{% endif %}
Timestamps: {{ time_instruction }}

Return JSON matching the schema. Requirements:
1. BASICS: on-screen text and where it sits (HUD, subtitles, prompts, overlays, watermarks).
2. FIRST 7 SECONDS: one entry per second.
3. EVENTS: every notable event to the end. The same event type can happen many
   times in one video (a single boss fight can contain 50 parries). Report every
   occurrence as its own event with its own timestamp. Never merge repeats into
   one event, summarise them as a group, or stop after the first few. Give the
   moment each one starts as precisely as the footage allows. Use only the event
   types listed above.
4. SECTIONS: the main parts of the video in order, with start and end times,
   as segments of kind "section".
{% if facts -%}
5. FACT PROPOSALS: for each fact below, propose a value with evidence timestamps,
   following that fact's instructions:
{% for f in facts %}   - {{ f.key }} ({{ f.label }}, {{ f.type }}): {{ f.guidance }}
{% endfor %}
{%- else -%}
5. FACT PROPOSALS: none for this video. Return an empty list.
{% endif -%}
6. PEAK: the single most striking 2 to 3 seconds, as one segment of kind "peak".
7. FRAMING: for each event, would a centered 9:16 crop cut off the key action?
8. AUDIO: what is audible and what is most prominent at key moments.
9. FIRST AND LAST FRAME: one sentence each.
