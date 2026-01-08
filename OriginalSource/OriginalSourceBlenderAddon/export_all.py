import bpy
from pathlib import Path

for col in bpy.data.collections:
    if col.library:
        continue
    if col.override_library:
        continue
    if not col.exporters:
        continue

    with bpy.context.temp_override(collection=col):
        bpy.ops.collection.export_all()