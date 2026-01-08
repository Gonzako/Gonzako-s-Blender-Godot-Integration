import bpy
import os
import json
from pathlib import Path
import fnmatch
import subprocess
from pprint import pprint
import shutil

bl_info = {
    "name": "glTF Extension for i/o with Godot",
    "category": "Export",
    "version": (0, 0, 2),
    "blender": (4, 4, 0),
    'location': 'File > Export > glTF 2.0',
    'description': 'Example addon to add a custom extension to an exported glTF file.',
    'tracker_url': "https://github.com/KhronosGroup/glTF-Blender-IO/issues/",  # Replace with your issue tracker
    'isDraft': True,
    'developer': "Simon Thommes", # Replace this
    'url': 'https://studio.blender.org/',  # Replace this
}

# glTF extensions are named following a convention with known prefixes.
# See: https://github.com/KhronosGroup/glTF/tree/main/extensions#about-gltf-extensions
# also: https://github.com/KhronosGroup/glTF/blob/main/extensions/Prefixes.md
glTF_extension_name = "EXT_example_extension"

# Support for an extension is "required" if a typical glTF viewer cannot be expected
# to load a given model without understanding the contents of the extension.
# For example, a compression scheme or new image format (with no fallback included)
# would be "required", but physics metadata or app-specific settings could be optional.
extension_is_required = False

EXCLUDE_LAYER_COLLECTIONS = set()

def split_id_name(name):
    if not '.'in name:
        return (name, None)
    name_el = name.split('.')
    extension = name_el[-1]
    if not extension.isdigit():
        return (name, None)
    name_string = '.'.join(name_el[:-1])
    return (name_string, extension)

def data_snapshot():

    data = set()
    for attr in dir(bpy.data):
        if not type(getattr(bpy.data, attr)) == type(bpy.data.scenes):
            continue
        data |= set(getattr(bpy.data, attr))

    return data

def remove_ids(ids):
    for id in ids:
        for attr in dir(bpy.data):
            if not type(getattr(bpy.data, attr)) == type(bpy.data.scenes):
                continue
            if id in getattr(bpy.data, attr)[:]:
                exec(f'bpy.data.{attr}.remove(id)')

def get_asset_index(self):
    collection = self.id_data
    if 'asset_id' not in collection.keys():
        return ''
    return collection['asset_id']
class GLTFIO_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    project_dir: bpy.props.StringProperty(  name='Project Path',
                                            default='',
                                            subtype='DIR_PATH',
                                            description='Path to the project directory. (Default is Blender Project, if one is found)'
                                            )
    source_dir_rel: bpy.props.StringProperty(   name='Source Subpath',
                                                default='',
                                                description='Source directory subpath, relative to Project directory'
                                                )
    target_dir_rel: bpy.props.StringProperty(   name='Target Subpath',
                                                default='game',
                                                description='Target directory subpath, relative to Blender Project directory'
                                                )

    def draw(self, context):
        layout = self.layout
        project_dir = project_root()
        if not project_dir:
            project_dir = os.path.realpath(bpy.path.abspath('//'))

        row = layout.row()
        row.alert = not(Path(project_dir).exists())
        row.prop(self, 'project_dir', placeholder=project_dir)
        layout.prop(self, 'source_dir_rel')
        row = layout.row()
        row = row.split(factor=0.25)
        row.enabled = False
        row.label()
        row.label(text=str(Path(project_dir).joinpath(self.source_dir_rel)))
        layout.prop(self, 'target_dir_rel')
        row = layout.row()
        row = row.split(factor=0.25)
        row.enabled = False
        row.label()
        row.label(text=str(Path(project_dir).joinpath(self.target_dir_rel)))
        
        split = layout.split()
        split.operator('gltfio.cleanup_asset_index')
        split.operator('gltfio.cleanup_material_index')

class GLTFIO_PT_gltfio_export_panel(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_label = "Asset Export"
    bl_category = "Asset Export"

    def draw(self, context):
        layout = self.layout
        addon_prefs = bpy.context.preferences.addons[__package__].preferences
        gltfio_props = context.scene.gltfIOGodotProperties

        initialization_header, initialization_panel = layout.panel('init_panel', default_closed=False)
        initialization_header.label(text='Export Initialization')

        if initialization_panel:
            initialization_panel.prop(gltfio_props, 'export_type')
            if gltfio_props.export_type=='ASSET':
                initialization_panel.prop(gltfio_props, 'root_type')
                initialization_panel.prop(gltfio_props, 'append_parent_collection')
            initialization_panel.operator("gltfio.initialize_export")

        layout.separator()
        op = layout.operator("gltfio.export", text='Export All', icon='EXPORT')
        op.export_context = 'ALL'
        if gltfio_props.export_type == 'ASSET':
            op = layout.operator("gltfio.export", text='Export Single', icon='DOT')
            op.export_context = 'SINGLE'
            op = layout.operator("gltfio.export", text='Export Children', icon='OUTLINER')
            op.export_context = 'CHILDREN'

        batch_export_header, batch_export_panel = layout.panel('batch_export_panel', default_closed=True)
        batch_export_header.label(text='Batch Export')

        if batch_export_panel:
            batch_export_panel.prop(gltfio_props, 'search_root_dir', placeholder=str(project_root()))
            batch_export_panel.prop(gltfio_props, 'filename_filter')
            if gltfio_props.export_progress == 0.:
                op = batch_export_panel.operator('gltfio.batch_export', icon="DUPLICATE")
            else:
                row = batch_export_panel.row()
                row.enabled = False
                row.prop(gltfio_props, 'export_progress')

EXPORT_TYPES = [
            ('NONE', 'None', '', 'NONE', 0),
            ('ANIMATION', 'Animation', '', 'RENDER_ANIMATION', 1),
            ('ASSET', 'Asset', '', 'ASSET_MANAGER', 2),
            ('CHARACTER', 'Character', '', 'OUTLINER_OB_ARMATURE', 3),
        ]

ROOT_TYPES = [
            ('NONE', 'None', '', 'NONE', 0),
            ('STATIC', 'Static', '', 'MESH_PLANE', 1),
            ('PASS_THROUGH', 'Pass-Through', '', 'SELECT_SET', 2),
        ]

ANIM_TYPES = [
            ('NONE', 'None', '', 'NONE', 0),
            ('ACTN', 'Action', '', 'ACTION', 1),
            ('SYNC', 'Synchronized Action', '', 'UV_SYNC_SELECT', 2),
            ('LOOP', 'Loop', '', 'FILE_REFRESH', 3),
            ('POSE', 'Single Pose', '', 'POSE_HLT', 4),
            ('CINE', 'Cinematic', '', 'SEQUENCE', 5),
        ]

def update_export_type(self, context):
    self.id_data['asset_type'] = self.export_type

def update_root_type(self, context):
    self.id_data['root_type'] = self.root_type

def update_anim_type(self, context):
    self.id_data['anim_type'] = self.anim_type
class gltfIOGodotProperties(bpy.types.PropertyGroup):
    export_type: bpy.props.EnumProperty(
        name='File Type',
        items=EXPORT_TYPES,
    )
    root_type: bpy.props.EnumProperty(
        name='Root Type',
        items=ROOT_TYPES,
    )
    asset_name: bpy.props.StringProperty(
        name='Asset Name',
        default=''
    )
    asset_id: bpy.props.StringProperty(
        name='Asset ID',
        get=get_asset_index
    )
    append_parent_collection: bpy.props.BoolProperty(
        name='Append Parent Collection to Path',
        default=True,
        description='Append the parent collection of the asset to the export path as additional directory layer if asset collection as a single parent.'
    )

    # Settings for batch export operator
    search_root_dir: bpy.props.StringProperty(
        name="Directory",
        default='',
        subtype="DIR_PATH",
    )
    filename_filter: bpy.props.StringProperty(
        name="Filter",
        default='*-anim.blend',
    )
    export_progress: bpy.props.IntProperty(
        name='Batch Export',
        default=0,
        min=0,
        max=100,
        subtype="PERCENTAGE"
    )

class gltfIOFileFilterResult(bpy.types.PropertyGroup):
    path: bpy.props.StringProperty(
        name='File Path',
    )
    export: bpy.props.BoolProperty(
        name="Export",
        default=True,
    )

class GLTFIO_UL_file_filter_uilist(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        op = data
        f = item
        gltfio_props = context.scene.gltfIOGodotProperties

        if gltfio_props.search_root_dir:
            search_dir = bpy.path.abspath(gltfio_props.search_root_dir)
        else:
            search_dir = project_root()
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.label(text=f.name)
            path = str(Path(f.path).parent)
            if search_dir:
                path = str(Path(path).relative_to(search_dir))
            row.label(text=path)
            row.prop(f, "export", text="")
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)

class gltfIOGodotAssetProperties(bpy.types.PropertyGroup):
    export_type: bpy.props.EnumProperty(
        name='Asset Type',
        items=EXPORT_TYPES,
        update=update_export_type,
    )
    root_type: bpy.props.EnumProperty(
        name='Root Type',
        items=ROOT_TYPES,
        update=update_root_type,
    )
    anim_type: bpy.props.EnumProperty(
        name='Animation Type',
        items=ANIM_TYPES,
        update=update_anim_type,
    )
    asset_name: bpy.props.StringProperty(
        name='Asset Name',
        default=''
    )
    asset_id: bpy.props.StringProperty(
        name='Asset ID',
        get=get_asset_index
    )
    append_parent_collection: bpy.props.BoolProperty(
        name='Append Parent Collection to Path',
        default=True,
        description='Append the parent collection of the asset to the export path as additional directory layer if asset collection as a single parent.'
    )
    placeholder_materials: bpy.props.BoolProperty(
        name='Use Placeholder Materials',
        default=False,
        description='Use placeholder materials that reference the original material by ID (always the case for linked materials).'
    )

def project_root():
    addon_prefs = bpy.context.preferences.addons[__package__].preferences

    if addon_prefs.project_dir:
        return addon_prefs.project_dir

    path = '//'
    
    while not '.blender_project' in os.listdir(os.path.realpath(bpy.path.abspath(path))):
        if os.path.realpath(bpy.path.abspath(path)) == os.path.realpath(bpy.path.abspath(path+'../')):
            return None
        path += '../'
    return os.path.realpath(bpy.path.abspath(path))

def generate_id(data_block):
    asset_id = str(os.urandom(8).hex())
    print(f'Assign asset ID `{asset_id}` to {data_block.name}')
    data_block['asset_id'] = asset_id
    return asset_id

def read_asset_info_from_index(asset_id, index_type='asset_index'):
    assets = load_asset_index(index_type)
    if not asset_id in assets.keys():
        return None
    return assets[asset_id]

def generate_asset_info(collection, export_settings):
    addon_prefs = bpy.context.preferences.addons[__package__].preferences
    props = collection.gltfIOGodotAssetProperties
    path = Path(export_settings['gltf_filepath'])
    path = path.relative_to(Path(project_root()).joinpath(addon_prefs.target_dir_rel))
    asset_info = {collection["asset_id"]: {
            "name": props.asset_name,
            "filepath": str(path)
            }
        }
    return asset_info

def load_asset_index(index_type='asset_index'):
    addon_prefs = bpy.context.preferences.addons[__package__].preferences
    project_dir = Path(project_root())
    if not project_dir:
        print("Couldn't find project root!")
        return None
    path = project_dir / addon_prefs.target_dir_rel / f'{index_type}.json'
    if not path.is_file():
        print(f"Couldn't find {index_type}.json!")
        return dict()
    with open(str(path)) as file:
        data = json.load(file)
    return data['assets']

def write_asset_index(assets, overwrite=False, index_type='asset_index'):
    addon_prefs = bpy.context.preferences.addons[__package__].preferences
    print('WRITING TO ASSET INDEX JSON')
    project_dir = Path(project_root())
    if not project_dir:
        return None
    path = project_dir / addon_prefs.target_dir_rel / f'{index_type}.json'
    if not path.is_file():
        data = dict()
    else:
        data = json.load(open(str(path)))
    if not "assets" in data.keys() or overwrite:
        data["assets"] = dict()
    for k, v in assets.items():
        data["assets"][k] = v
    with open(path, 'w') as file:
        try:
            file.write(json.dumps(data, indent=4))
        except OSError as err:
            print("Error writing index JSON: % s" % err)

def init_export(context):
    gltfio_props = context.scene.gltfIOGodotProperties

    if gltfio_props.export_type == 'ANIMATION':
        init_animation_export(context)
    elif gltfio_props.export_type == 'ASSET':
        init_asset_export(context)
    elif gltfio_props.export_type == 'CHARACTER':
        init_character_export(context)

def get_file_anim_prefix():
    file_name = bpy.path.basename(bpy.data.filepath)

    if '-' not in file_name:
        return 'NONE'

    prefix = file_name.split('-')[0]
    if not prefix in [item[0] for item in ANIM_TYPES]:
        return 'NONE'

    return prefix

def init_animation_export(context):
    for ob in bpy.data.objects:
        if not ob.type=='ARMATURE':
            continue
        if ob.library:
            continue
        if not ob.name.startswith('RIG-'):
            continue
        if not ob.animation_data:
            continue
        if not ob.animation_data.action:
            continue

        asset_col = None
        for col in bpy.data.collections:
            if col.name.split('-')[0] not in ['CH', 'PR']:
                continue
            if ob in col.all_objects[:]:
                asset_col = col
                break
        if not asset_col:
            continue

        col_name = f"EXPORT-{'-'.join(ob.name.split('-')[1:])}"
        collection = bpy.data.collections.get(col_name)
        if not collection:
            collection = bpy.data.collections.new(col_name)
        if not ob in collection.objects[:]:
            collection.objects.link(ob)
        if not collection in context.scene.collection.children[:]:
            context.scene.collection.children.link(collection)
        exporter = None
        for ex in collection.exporters:
            if ex.export_properties.export_format == 'GLTF_SEPARATE':
                exporter = ex
        if not exporter:
            with context.temp_override(collection=collection):
                bpy.ops.collection.exporter_add(name='IO_FH_gltf2')
            exporter = collection.exporters[-1]
        
        # init exporter settings
        collection_props = collection.gltfIOGodotAssetProperties
        collection_props.export_type = 'ANIMATION'
        prefix = get_file_anim_prefix()
        if prefix:
            collection_props.anim_type = prefix
        if ob.animation_data:
            if ob.animation_data.action:
                collection_props.asset_name = ob.animation_data.action.name
        if 'asset_id' in asset_col.keys():
            collection['ref_asset_id'] = asset_col['asset_id']
        collection_props.append_parent_collection = False
        init_export_collection(collection, exporter, include_file_name=False)
    return

def find_parent_collections(collection, context = None):
    if not collection:
        return []
    if not context:
        context = bpy.context
    
    parents = []
    for col in bpy.data.collections[:]:
        if col.library:
            continue
        if collection in col.children[:]:
            parents.append(col)

    return parents

def init_asset_export(context):
    gltfio_props = context.scene.gltfIOGodotProperties
    for collection in bpy.data.collections:
        if collection.library:
            continue
        
        include_file_name=True
        if collection.name.startswith('LI-'):
            pass
        elif collection.name.startswith('SE-'):
            include_file_name=False
        elif collection.name.startswith('SL-'):
            include_file_name=False
        elif collection.name.startswith('PR-'):
            include_file_name=False
        else:
            continue
         
        exporter = None
        for ex in collection.exporters:
            if ex.export_properties.export_format == 'GLTF_SEPARATE':
                exporter = ex
        if not exporter:
            with context.temp_override(collection=collection):
                bpy.ops.collection.exporter_add(name='IO_FH_gltf2')
            exporter = collection.exporters[-1]

        # init exporter settings
        collection_props = collection.gltfIOGodotAssetProperties
        collection_props.export_type = 'ASSET'
        collection_props.root_type = gltfio_props.root_type
        collection_props.append_parent_collection = gltfio_props.append_parent_collection
        collection_props.asset_name = collection.name
        init_export_collection(collection, exporter, include_file_name=include_file_name)
    return

def init_character_export(context):
    for collection in bpy.data.collections:
        if collection.library:
            continue
        if not collection.name.startswith('CH-'):
            continue
         
        exporter = None
        for ex in collection.exporters:
            if ex.export_properties.export_format == 'GLTF_SEPARATE':
                exporter = ex
        if not exporter:
            with context.temp_override(collection=collection):
                bpy.ops.collection.exporter_add(name='IO_FH_gltf2')
            exporter = collection.exporters[-1]

        # init exporter settings
        collection_props = collection.gltfIOGodotAssetProperties
        collection_props.export_type = 'CHARACTER'
        name, extension = split_id_name(collection.name)
        collection_props.asset_name = '-'.join(name.split('-')[1:])
        collection_props.append_parent_collection = False
        init_export_collection(collection, exporter, include_file_name=False)
    return

def init_export_collection(collection, exporter=None, include_file_name=True):
    addon_prefs = bpy.context.preferences.addons[__package__].preferences
    if not collection:
        return
    if not collection.exporters:
        return
    if not exporter:
        exporter = collection.exporters[collection.active_exporter_index]

    collection_props = collection.gltfIOGodotAssetProperties
    export_settings = exporter.export_properties

    project_dir = project_root()
    if not project_dir:
        print('ERROR: No project root directory could be identified!')
        return
    else:
        project_dir = Path(project_dir)

    export_settings.export_format = 'GLTF_SEPARATE'
    export_settings.export_extras = True
    export_settings.at_collection_center = False #TODO get proper method for collection center
    filepath = Path(bpy.data.filepath)

    rel_path = filepath.parent.relative_to(project_dir.joinpath(addon_prefs.source_dir_rel))
    target_root_dir = project_dir.joinpath(addon_prefs.target_dir_rel)
    output_path = target_root_dir.joinpath(rel_path)

    if include_file_name:
        output_path = output_path.joinpath(filepath.stem)
    if collection_props.append_parent_collection:
        parent_cols = find_parent_collections(collection)
        if len(parent_cols) == 1:
            output_path = output_path.joinpath(parent_cols[0].name)
    output_path = output_path.joinpath(collection_props.asset_name+'.gltf')

    if collection_props.export_type == 'NONE':
        return
    elif collection_props.export_type == 'ANIMATION':
        export_settings.export_sampling_interpolation_fallback = 'STEP'
        export_settings.export_animation_mode = 'BROADCAST'
        export_settings.export_frame_range = True
        export_settings.export_anim_slide_to_zero = True
        export_settings.export_negative_frame = 'CROP'
        export_settings.export_anim_single_armature = False

        export_settings.export_action_filter = True
        action_filter = bpy.context.scene.gltf_action_filter
        for item in action_filter:
            if not item.action:
                item.keep = False
                continue
            item.keep = item.action.name == collection_props.asset_name
    elif collection_props.export_type in ['ASSET', 'CHARACTER']:
        export_settings.export_animations = False
        if 'export_texture_dir' in export_settings.keys():
            export_settings.export_texture_dir = ''
        export_settings.export_apply = True
        export_settings.export_attributes = True

    if not 'asset_id' in collection.keys():
        generate_id(collection)

    output_path = bpy.path.relpath(str(output_path))
    export_settings.filepath = output_path

class GLTFIO_OT_initialize_export(bpy.types.Operator):
    """ 
    """
    bl_idname = "gltfio.initialize_export"
    bl_label = "Initialize Export"
    bl_description = "Initialize the export setup and settings based on the selected export type."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):

        props = context.scene.gltfIOGodotProperties

        return bool(props.export_type != 'NONE')

    def execute(self, context):

        init_export(context)

        return {"FINISHED"}
class GLTFIO_OT_initialize_export_collection(bpy.types.Operator):
    """ 
    """
    bl_idname = "gltfio.initialize_export_collection"
    bl_label = "Initialize Export Collection"
    bl_description = "Initialize the collection export setup and settings based on the selected export type."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):

        props = context.collection.gltfIOGodotAssetProperties

        return bool(props.export_type != 'NONE')

    def execute(self, context):

        collection = context.collection
        include_file_name = True

        if collection.name.startswith('LI-'):
            pass
        elif collection.name.startswith('SE-'):
            include_file_name=False
        elif collection.name.startswith('SL-'):
            include_file_name=False
        elif collection.name.startswith('PR-'):
            include_file_name=False

        print('HUH')

        init_export_collection(collection, include_file_name = include_file_name)

        return {"FINISHED"}

def export_collection(context, collection):
    if collection.library:
        return
    if collection.override_library:
        return
    if collection.exporters:
        l_cols = find_layer_collections_by_collection(collection, bpy.context.view_layer.layer_collection)
        if not l_cols:
            return
        exclude = l_cols[0].exclude
        if exclude:
            l_cols[0].exclude = False
            bpy.context.view_layer.update()
        with context.temp_override(collection=collection):
            bpy.ops.collection.export_all()
        if exclude:
            l_cols[0].exclude = True

def recursive_export_all_collection(context, collection):
    export_collection(context, collection)
    for col in collection.children:
        recursive_export_all_collection(context, col)

class GLTFIO_OT_export(bpy.types.Operator):
    """ 
    """
    bl_idname = "gltfio.export"
    bl_label = "Export"
    bl_description = "Initialize the collection export setup and settings based on the selected export type."
    bl_options = {"REGISTER", "UNDO"}

    export_context: bpy.props.EnumProperty(
        name='Export Context',
        items=[
            ('ALL', 'All', '', 'NONE', 0),
            ('SINGLE', 'Single', '', 'NONE', 1),
            ('CHILDREN', 'Children', '', 'NONE', 2),
        ]
    )

    @classmethod
    def poll(cls, context):

        return bpy.ops.wm.collection_export_all.poll()

    def execute(self, context):

        if self.export_context=='ALL':
            recursive_export_all_collection(context, context.scene.collection)
        elif self.export_context=='SINGLE':
            export_collection(context, context.collection)
        elif self.export_context=='CHILDREN':
            recursive_export_all_collection(context, context.collection)

        return {"FINISHED"}

class GLTFIO_OT_cleanup_asset_index(bpy.types.Operator):
    """ 
    """
    bl_idname = "gltfio.cleanup_asset_index"
    bl_label = "Cleanup Asset Index"
    bl_description = "Clean up the asset index file by removing unused entries."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(project_root())

    def execute(self, context):

        asset_index = load_asset_index()
        if not asset_index:
            return {"CANCELLED"}

        gltf_list = list_project_files_recursive(project_root(), '*.gltf')
        found_assets = dict()

        for path in gltf_list:
            try:
                with open(str(path)) as file:
                    data = json.load(file)
            except:
                print(f'WARNING: Could not read `{path}`')
                continue
            scene_info = data['scenes'][0]
            if 'extras' not in scene_info.keys():
                print(f"Didn't find extras on scene for `{path}`")
                continue
            if 'asset_type' not in scene_info['extras'].keys():
                print(f"Didn't find asset type on scene for `{path}`")
                continue
            if scene_info['extras']['asset_type'] != 'ASSET':
                continue
            if 'asset_id' not in scene_info['extras'].keys():
                print(f"Didn't find asset ID on scene for `{path}`")
                continue
            found_assets[scene_info['extras']['asset_id']] = path

        for k in found_assets.keys():
            if k not in asset_index.keys():
                print(f"Missing {k} at `{found_assets[k]}` in asset index!")
        
        del_ids = set()
        for k in asset_index.keys():
            if k not in found_assets.keys():
                del_ids.add(k)

        if not del_ids:
            return {"FINISHED"}

        print("Removing Asset Index Entries:")
        for k in del_ids:
            print(k)
            pprint(asset_index.pop(k))
        
        write_asset_index(asset_index, overwrite=True)

        return {"FINISHED"}

class GLTFIO_OT_cleanup_material_index(bpy.types.Operator):
    """ 
    """
    bl_idname = "gltfio.cleanup_material_index"
    bl_label = "Cleanup Material Index"
    bl_description = "Clean up the material index file by removing unused entries."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(project_root())

    def execute(self, context):

        asset_index = load_asset_index(index_type='material_index')
        if not asset_index:
            return {"CANCELLED"}

        gltf_list = list_project_files_recursive(project_root(), '*.gltf')
        found_assets = dict()

        for path in gltf_list:
            try:
                with open(str(path)) as file:
                    data = json.load(file)
            except:
                print(f'WARNING: Could not read `{path}`')
                continue
            if 'materials' not in data.keys():
                continue
            for mat_info in data['materials']:
                if 'extras' not in mat_info.keys():
                    print(f"Didn't find extras on material {mat_info['name']} at `{path}`")
                    continue
                if 'asset_id' not in mat_info['extras'].keys():
                    print(f"Didn't find asset ID on material {mat_info['name']} at `{path}`")
                    continue
                found_assets[mat_info['extras']['asset_id']] = path

        for k in found_assets.keys():
            if k not in asset_index.keys():
                print(f"Missing {k} at `{found_assets[k]}` in material index!")
        
        del_ids = set()
        for k in asset_index.keys():
            if k not in found_assets.keys():
                del_ids.add(k)

        if not del_ids:
            return {"FINISHED"}

        print("Removing Material Index Entries:")
        for k in del_ids:
            print(k)
            pprint(asset_index.pop(k))
        
        write_asset_index(asset_index, overwrite=True, index_type='material_index')

        return {"FINISHED"}

def list_project_files_recursive(dir, filter: str):
    match_files = []
    files = []
    for f in os.scandir(dir):
        if f.is_dir():
            match_files += list_project_files_recursive(f.path, filter)
        else:
            files += [str(Path(f.path))]
    match_files += fnmatch.filter(files, filter)
    return match_files

def export_in_subprocess(file_path):
    blender_executable = bpy.app.binary_path

    try:
        subprocess.run(
            [
                blender_executable,
                str(file_path),
                "--background",
                "--factory-startup",
                "--python",
                Path(__file__).parent / 'export_all.py',
                "--",
                "-b"
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as ex:
        print("Error running Blender: ", ex)
        return []


class GLTFIO_OT_batch_export(bpy.types.Operator):
    """ 
    """
    bl_idname = "gltfio.batch_export"
    bl_label = "Batch Export"
    bl_description = "Export related assets that depend on changes to this asset."
    bl_options = {"REGISTER", "UNDO"}

    file_list: bpy.props.CollectionProperty(type=gltfIOFileFilterResult)
    active_file_index: bpy.props.IntProperty()

    _progress = 0.
    _updating = False
    _calcs_done = False
    _timer = None

    @classmethod
    def poll(cls, context):
        return True

    def do_calcs(self):
        if self.active_file_index == len(self.file_list):
            self._calcs_done = True
            return

        f = self.file_list[self.active_file_index]
        if f.export:
            export_in_subprocess(f.path)
            self._progress += 1. / len([f for f in self.file_list if f.export])

        self.active_file_index += 1

    def modal(self, context, event):
        gltfio_props = context.scene.gltfIOGodotProperties
        if event.type == 'TIMER' and not self._updating:
            self._updating = True
            self.do_calcs()
            gltfio_props.export_progress = int(100. * self._progress)
            self._updating = False
            for area in context.screen.areas:
                area.tag_redraw()
        if self._calcs_done:
            return self.cancel(context)

        return {'PASS_THROUGH'}

    def execute(self, context):
        if len([f for f in self.file_list if f.export]) == 0:
            return {'FINISHED'}
        gltfio_props = context.scene.gltfIOGodotProperties
        context.window_manager.modal_handler_add(self)
        self._updating = False
        self._timer = context.window_manager.event_timer_add(0.5, window=context.window)
        
        self.active_file_index = 0
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        gltfio_props = context.scene.gltfIOGodotProperties
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        self._progress = 0.
        gltfio_props.export_progress = 0
        return
    
    def invoke(self, context, event):
        gltfio_props = context.scene.gltfIOGodotProperties

        for i in range(len(self.file_list)):
            self.file_list.remove(0)
        self.active_file_index = 0

        if gltfio_props.search_root_dir:
            search_dir = bpy.path.abspath(gltfio_props.search_root_dir)
        else:
            search_dir = project_root()

        file_list = list_project_files_recursive(search_dir, '*'+gltfio_props.filename_filter)
        file_list.sort()

        for f in file_list:
            new_entry = self.file_list.add()
            new_entry.name = Path(f).name
            new_entry.path = f

        wm = context.window_manager
        return wm.invoke_props_dialog(self, width = 800)

    def draw(self, context):
        layout = self.layout
        
        layout.template_list("GLTFIO_UL_file_filter_uilist", "", self, "file_list", self, "active_file_index")
    
classes = [
    gltfIOGodotProperties,
    gltfIOGodotAssetProperties,
    gltfIOFileFilterResult,
    GLTFIO_preferences,
    GLTFIO_UL_file_filter_uilist,
    GLTFIO_PT_gltfio_export_panel,
    GLTFIO_OT_initialize_export,
    GLTFIO_OT_initialize_export_collection,
    GLTFIO_OT_export,
    GLTFIO_OT_batch_export,
    GLTFIO_OT_cleanup_asset_index,
    GLTFIO_OT_cleanup_material_index,
]

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Collection.gltfIOGodotAssetProperties = bpy.props.PointerProperty(type=gltfIOGodotAssetProperties)
    bpy.types.Scene.gltfIOGodotProperties = bpy.props.PointerProperty(type=gltfIOGodotProperties)
    bpy.types.COLLECTION_PT_exporters.prepend(draw_export_collection)

def unregister():
    for c in classes:
        bpy.utils.unregister_class(c)
    del bpy.types.Collection.gltfIOGodotAssetProperties
    del bpy.types.Scene.gltfIOGodotProperties
    bpy.types.COLLECTION_PT_exporters.remove(draw_export_collection)

def draw_export_collection(self, context):
    collection = context.collection
    if not collection:
        return
    if not collection.exporters:
        return
    active_exporter = collection.exporters[collection.active_exporter_index]
    layout = self.layout

    props = context.collection.gltfIOGodotAssetProperties

    layout.prop(props, 'export_type')
    if props.export_type in ['ASSET', 'CHARACTER']:
        layout.prop(props, 'root_type')
        layout.prop(props, 'append_parent_collection')
        layout.prop(props, 'placeholder_materials')
    elif props.export_type=='ANIMATION':
        layout.prop(props, 'anim_type')
    layout.operator('gltfio.initialize_export_collection')
    layout.prop(props, 'asset_name')
    row = layout.row()
    row.enabled = False
    row.prop(props, 'asset_id')

def init_export_setup():
    print('Initializing Export Setup')

def pre_process_objects(collection):
    for ob in collection.all_objects:

        mark_collision_info(ob)
        
        mark_visibility_info(ob)

        # assign instance IDs and temporarily disable instancing
        if ob.instance_type == 'COLLECTION':
            if not ob.instance_collection:
                continue
            if not 'asset_id' in ob.instance_collection.keys():
                continue
            if not ob.instance_collection['asset_id']:
                continue
            ob.instance_type = 'NONE'
            ob['instance_asset_id'] = ob.instance_collection['asset_id']
    
def pre_process_materials(collection):
    props = collection.gltfIOGodotAssetProperties

    mats = set()
    for ob in collection.all_objects:
        for mat in [mslot.material for mslot in ob.material_slots]:
            if not mat:
                continue
            if 'asset_id' not in mat.keys():
                generate_id(mat)
            mats.add(mat)
            mark_material_info(mat)
    if not mats:
        return
    
    addon_prefs = bpy.context.preferences.addons[__package__].preferences
    path = Path(bpy.data.filepath)
    path = path.parent / path.stem
    path = path.relative_to(Path(project_root()))
        
    include_file_name=False
    if collection.name.startswith('LI-'):
        include_file_name=True

    if not include_file_name:
        path = path.parent

    assets = dict()
    for mat in mats:
        if mat.library or props.placeholder_materials:
            dummy_mat = bpy.data.materials.new(f"DUMMY-{mat.name}")
            mat.user_remap(dummy_mat)
            dummy_mat['asset_id'] = mat['asset_id']
            continue
        assets[mat['asset_id']] = {
            'name': mat.name,
            'filepath': str(path / (mat.name))
        }
    
    write_asset_index(assets, index_type='material_index')

def post_process_materials(collection):
    for mat in bpy.data.materials:
        if mat.name.startswith("DUMMY"):
            mat.user_remap(bpy.data.materials.get('-'.join(mat.name.split('-')[1:])))
            bpy.data.materials.remove(mat)


def import_node_group(name, path):

    with bpy.data.libraries.load(path, link=True, relative=True) as (data_src, data_dst):
        data_dst.node_groups = [name]
    
    return bpy.data.node_groups.get(name)

def ensure_node_group(name, path=''):
    ng = bpy.data.node_groups.get(name)
    if ng:
        return ng
    
    if not path:
        path=str(Path(project_root()) / 'assets/nodes/pipeline.blend')

    ng = import_node_group(name, path)
    
    return ng

def pre_process_vertex_colors(collection):
    export_settings = collection.exporters[collection.active_exporter_index].export_properties
    
    export_settings.export_vertex_color = 'NAME'
    export_settings.export_vertex_color_name = 'COLOR'

    ng_name = 'GLTFIO-write_vertex_color'
    ng = ensure_node_group(ng_name)

    for ob in collection.all_objects:
        if ob.type not in ['MESH', 'CURVE', 'CURVES']:
            continue
        mod = ob.modifiers.new(name=ng_name,type='NODES')
        mod.node_group = ng

def post_process_vertex_colors(collection):
    ng_name = 'GLTFIO-write_vertex_color'

    for ob in collection.all_objects:
        if ob.type not in ['MESH', 'CURVE', 'CURVES']:
            continue
        for mod in ob.modifiers:
            if mod.type != 'NODES':
                continue
            if not mod.node_group:
                continue
            if mod.node_group.name == ng_name:
                ob.modifiers.remove(mod)

def find_layer_collections_by_collection(collection, layer_collection):
    layer_collection_list = []
    for lcol in layer_collection.children:
        if lcol.collection == collection:
            layer_collection_list.append(lcol)
        layer_collection_list = layer_collection_list + find_layer_collections_by_collection(collection, lcol)
    return layer_collection_list

def include_recursive(layer_collection, collection):
    global EXCLUDE_LAYER_COLLECTIONS
    if layer_collection.exclude:
        layer_collection.exclude = False
        EXCLUDE_LAYER_COLLECTIONS.add(layer_collection)
    for lcol in layer_collection.children:
        include_recursive(lcol, collection)

def exclude_recursive(layer_collection):
    global EXCLUDE_LAYER_COLLECTIONS
    if layer_collection in EXCLUDE_LAYER_COLLECTIONS:
        layer_collection.exclude = True
    for lcol in layer_collection.children:
        exclude_recursive(lcol)

def pre_process_collections(collection):
    global EXCLUDE_LAYER_COLLECTIONS
    EXCLUDE_LAYER_COLLECTIONS = set()
    layer_collection_list = find_layer_collections_by_collection(collection, bpy.context.view_layer.layer_collection)
    for lcol in layer_collection_list:
        include_recursive(lcol, collection)
    if EXCLUDE_LAYER_COLLECTIONS:
        bpy.context.view_layer.update()

def post_process_collections(collection):
    global EXCLUDE_LAYER_COLLECTIONS
    layer_collection_list = find_layer_collections_by_collection(collection, bpy.context.view_layer.layer_collection)
    for lcol in layer_collection_list:
        exclude_recursive(lcol)
    if EXCLUDE_LAYER_COLLECTIONS:
        bpy.context.view_layer.update()
    EXCLUDE_LAYER_COLLECTIONS = set()

def pre_export(export_settings):
    collection = bpy.data.collections[export_settings['gltf_collection']]

    if not 'asset_id' in collection.keys():
        asset_id = generate_id(collection)
    else:
        asset_id = collection['asset_id']

    collection_props = collection.gltfIOGodotAssetProperties

    if collection_props.export_type == 'ANIMATION':
        action_filter = bpy.context.scene.gltf_action_filter
        for item in action_filter:
            if not item.action:
                item.keep = False
                continue
            item.keep = item.action.name == collection_props.asset_name

        if collection_props.anim_type == 'LOOP':
            bpy.context.scene.frame_end += 1
    else:
        asset_info = generate_asset_info(collection, export_settings)

        path = asset_info[asset_id]['filepath']
        asset_info_r = read_asset_info_from_index(asset_id)

        if not asset_info_r:
            write_asset_index(asset_info)
        elif asset_info_r['filepath'] != str(path):
            asset_id = generate_id(collection)
            asset_info = generate_asset_info(collection, export_settings)
            write_asset_index(asset_info)
        elif asset_info_r['name'] != str(path):
            write_asset_index(asset_info)

    pre_process_collections(collection)

    pre_process_objects(collection)

    pre_process_materials(collection)

    pre_process_vertex_colors(collection)

    collection['asset_type'] = collection_props.export_type
    collection['root_type'] = collection_props.root_type
    
    # If the export directory does not exist, create it
    if not os.path.isdir(export_settings['gltf_filedirectory']):
        os.makedirs(export_settings['gltf_filedirectory'])
    if export_settings['gltf_format'] == "GLTF_SEPARATE" \
            and not os.path.isdir(export_settings['gltf_texturedirectory']):
        os.makedirs(export_settings['gltf_texturedirectory'])

def post_process_image_textures(export_settings):
    path = Path(export_settings['gltf_filepath'])

    with open(str(path)) as file:
        data = json.load(file)

    if not 'images' in data.keys():
        return
    
    root_dir = Path(project_root())
    addon_prefs = bpy.context.preferences.addons[__package__].preferences

    target_dir = root_dir / addon_prefs.target_dir_rel

    for image_info in data['images']:
        if not 'extras' in image_info.keys():
            print(f"Couldn't find extras on image {image_info['name']}")
            continue

        texture_dir = export_settings["gltf_texturedirectory"]
        if texture_dir:
            filepath = Path(os.path.realpath(bpy.path.abspath(f"//{texture_dir}/{image_info['uri']}", start=path.parent)))
        else:
            filepath = Path(os.path.realpath(bpy.path.abspath(f"//{image_info['uri']}", start=path.parent)))
        target_path = target_dir / image_info['extras']['source_path']
        print(f"Moving image texture file from {filepath} to {target_path}")

        target_path.parent.mkdir(parents=True, exist_ok=True)

        if filepath == target_path:
            continue

        # copy image file
        try:
            shutil.copy2(filepath, target_path)
        except OSError as err:
            print("Error: % s" % err)
            continue

        # change path in gltf
        uri = bpy.path.relpath(os.path.realpath(target_dir / image_info['extras']['source_path']), start=str(path.parent))
        image_info['uri'] = str(uri)[2:]

        # delete original
        try:
            os.remove(filepath)
        except OSError as err:
            print("Error: % s" % err)

        # remove previous parent folder if empty
        try:
            filepath.parent.rmdir()
        except:
            continue
    
    with open(path, 'w') as file:
        file.write(json.dumps(data, indent=4))

def post_export(export_settings):
    collection = bpy.data.collections[export_settings['gltf_collection']]

    collection_props = collection.gltfIOGodotAssetProperties

    for ob in bpy.data.objects:
        if 'instance_asset_id' in ob.keys():
            if ob.type == 'EMPTY':
                ob.instance_type = 'COLLECTION'

    if collection_props.export_type == 'ANIMATION':
        if collection_props.anim_type == 'LOOP':
            bpy.context.scene.frame_end -= 1
    
    post_process_collections(collection)

    post_process_materials(collection)

    post_process_vertex_colors(collection)

    post_process_image_textures(export_settings)


def mark_visibility_info(ob):
    visibility_info = dict()

    if not ob.visible_shadow:
        visibility_info['shadow'] = False

    if not visibility_info:
        if "visibility_info" in ob.keys():
            del ob["visibility_info"]
        return
    
    ob['visibility_info'] = visibility_info
    

def mark_collision_info(ob):
    if not ob.name.startswith('COL-'):
        if 'collision_info' in ob.keys():
            del ob['collision_info']
        return False

    for mod in ob.modifiers:
        if not mod.type == 'NODES':
            continue
        if not mod.node_group:
            continue
        if mod.node_group.name == 'GN-generate_collision_mesh':
            collision_info = {
                'type': 'MESH',
                'concave': mod['Socket_3'],
            }
            ob['collision_info'] = collision_info
            return True
        elif mod.node_group.name == 'GN-collision_primitive':
            collision_info = {
                'type': 'PRIMITIVE',
                'shape': mod['Socket_5'],
                'radius': mod['Socket_2'],
                'height': mod['Socket_3'],
                'size': mod['Socket_4'],
            }
            ob['collision_info'] = collision_info
            mod.node_group.interface_update(bpy.context)
            mod['Socket_6'] = True
            return True
    collision_info = {
        'type': 'MESH',
        'concave': True,
    }
    ob['collision_info'] = collision_info
    return True

def mark_material_info(material):
    if not material:
        return False
    if not material.node_tree:
        return False
    nt = material.node_tree
    n_out = None
    for n in nt.nodes:
        if n.type != 'OUTPUT_MATERIAL':
            continue
        if n.is_active_output:
            n_out = n
            break
    if not n_out:
        return False
    if not n_out.inputs[0].links:
        return False
    
    n_sh = n_out.inputs[0].links[0].from_node
    if n_sh.type != 'GROUP':
        return False
    mat_info = dict()
    for input in n_sh.inputs:
        if input.links:
            continue
        mat_info[input.name.lower().replace(' ', '_')] = input.default_value
    material['material_info'] = mat_info
    material.update_tag()
    return True

def find_image_from_socket(socket):
    if not socket.links:
        return None
    
    node = socket.links[0].from_node

    if node.type == 'TEX_IMAGE':
        if node.image:
            return node.image

    for input in node.inputs:
        image = find_image_from_socket(input)
        if image:
            return image
    return None

DEBUG = False

class glTF2ExportUserExtension:

    def __init__(self):
        # We need to wait until we create the gltf2UserExtension to import the gltf2 modules
        # Otherwise, it may fail because the gltf2 may not be loaded yet
        from io_scene_gltf2.io.com.gltf2_io_extensions import Extension
        self.Extension = Extension
        self.properties = bpy.context.scene.gltfIOGodotProperties

    def pre_export_hook(self, export_settings):
        pre_export(export_settings)

    def post_export_hook(self, export_settings):
        post_export(export_settings)

    def gather_image_hook(self, gltf2_image, b_image, blender_shader_sockets, export_settings):
        if DEBUG: print(f"Gather image {gltf2_image}")

        addon_prefs = bpy.context.preferences.addons[__package__].preferences

        s = blender_shader_sockets[0].socket
        # image = find_image_from_socket(s) # FAILS WHEN SOCKET IS INSIDE NODEGROUP
        # Doing ugly name lookup instead smh
        image = bpy.data.images.get(gltf2_image.uri.name)
        if image is None:
            image = [img for img in bpy.data.images if img.name.startswith(gltf2_image.uri.name+'.')][0]
        if not image:
            print(f"Couldn't find blender image {gltf2_image.uri.name} relating to socket {s}")
            return
        
        root_dir = Path(project_root())

        source_path_rel = Path(os.path.realpath(bpy.path.abspath(image.filepath))).relative_to(root_dir / addon_prefs.source_dir_rel)

        if not gltf2_image.extras:
            gltf2_image.extras = dict()
        gltf2_image.extras['source_path'] = str(source_path_rel)

    def gather_texture_hook(self, gltf2_texture, blender_shader_sockets, export_settings):
        if DEBUG: print(f"Gather texture {gltf2_texture}")

    def gather_texture_info_hook(self, gltf2_texture_info, blender_shader_sockets, export_settings):
        if DEBUG: print(f"Gather texture {gltf2_texture_info}")

    def gather_scene_hook(self, gltf2_scene, blender_scene, export_settings):
        if DEBUG: print(f'Gather scene: {gltf2_scene}; {blender_scene}')