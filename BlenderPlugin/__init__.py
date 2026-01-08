from pathlib import Path

import bpy

bl_info = {
    "name": "glTF Extension for i/o with Godot",
    "category": "Export",
    "version": (0, 0, 1),
    "blender": (5, 0, 1),
    "location": "File > Export > glTF 2.0",
    "description": "Blender to Godot scene integration. Thanks to Simon Thommes for working on the initial draft.",
    "tracker_url": "",  # Replace with your issue tracker
    "isDraft": True,
    "developer": "Gonzako",  # Replace this
    "url": "gonzako.com",  # Replace this
}


glTF_extension_name = "GONZ_blender_godot_extension"


def project_root():
    addon_prefs = bpy.context.preferences.addons[__package__].preferences

    if addon_prefs.project_dir:
        return addon_prefs.project_dir

    # This plugin assumes that the .blend files will be inside the godot project so it uses the project.godot file as a pointer
    path = Path(bpy.data.filepath).parent
    max_hops = 20
    curr_hops = 0
    while (not (path / "project.godot").exists()) and curr_hops < max_hops:
        path = path.parent
        curr_hops += 1

    if (path / "project.godot").exists():
        addon_prefs.project_dir = path

    return path

EXPORT_TYPES = [
            ('NONE', 'None', '', 'NONE', 0),
            #('ANIMATION', 'Animation', '', 'RENDER_ANIMATION', 1),
            ('ASSET', 'Asset', '', 'ASSET_MANAGER', 2),
            #('CHARACTER', 'Character', '', 'OUTLINER_OB_ARMATURE', 3),
        ]
ROOT_TYPES = [
            ('NONE', 'None', '', 'NONE', 0),
            ('STATIC', 'Static', '', 'MESH_PLANE', 1),
            ('PASS_THROUGH', 'Pass-Through', '', 'SELECT_SET', 2),
        ]

class GBGE_asset_properties(bpy.types.PropertyGroup):
    export_type: bpy.props.EnumProperty(
        name='File Type',
        items=EXPORT_TYPES,
    )
    root_type: bpy.props.EnumProperty(
        name='Root Type',
        items=ROOT_TYPES,
    )
    asset_id: bpy.props.StringProperty(
        name='Asset ID',
        get=get_asset_index
    )
    asset_name: bpy.props.StringProperty(
        name='Asset Name',
        default=''
    )

class GBGE_Godot_properties(bpy.types.PropertyGroup):
    export_type: bpy.props.EnumProperty(
        name='File Type',
        items=EXPORT_TYPES,
    )
    root_type: bpy.props.EnumProperty(
        name='Root Type',
        items=ROOT_TYPES,
    )
    asset_id: bpy.props.StringProperty(
        name='Asset ID',
        get=get_asset_index
    )
    asset_name: bpy.props.StringProperty(
        name='Asset Name',
        default=''
    )

class GBGE_preferences(bpy.types.AddonPreferences):
    project_dir: bpy.props.StringProperty(
        name="Project Path",
        default="",
        subtype="DIR_PATH",
        description="Path to the project directory. (Default is Godot Project, if one is found)",
    )

    source_dir_rel: bpy.props.StringProperty(
        name="Source Subpath",
        default="blender project",
        description="Source directory subpath, relative to Project directory",
    )

    target_dir_rel: bpy.props.StringProperty(
        name="Target Subpath",
        default="exported game",
        description="Target directory subpath, relative to Godots Project directory",
    )

    def draw(self, context):
        layout = self.layout
        project_dir = project_root()

        row = layout.row()
        row.alert = not(Path(project_dir).exists())
        row.prop(self,'project_dir',placeholder=project_dir)
        layout.prop(self,'source_dir_rel')
        row.enabled = False
        row = row.split(factor=0.25)
        row.label()
        row.label(text=str(Path(project_dir).joinpath(self.source_dir_rel)))
        layout.prop(self, 'target_dir_rel')
        row = layout.row()
        row = row.split(factor=0.25)
        row.enabled = False
        row.label()
        row.label(text=str(Path(project_dir).joinpath(self.target_dir_rel)))

class GBGE_OT_initialize_exports(bpy.types.Operator):
    """ 
    """
    bl_idname = "gbge.initialize_exports"
    bl_label = "Setup Exports"
    bl_description = "Initialize the export setup and settings based on the selected export type."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):

        props = context.scene.GBGE_Godot_properties

        return bool(props.export_type != 'NONE')

    def execute(self, context):
        bpy.ops.collection.exporter_add(name="IO_FH_gltf2")
        meshdata = context.collection.exporters[-1]
        meshdata.name = "GBGE_"+context.collection.name+"_mesh_export"
        
        collection_props = context.collection.GBGE_asset_properties 
        collection_props.export_type = 'ASSET'
        collection_props.root_type = context.scene.GBGE_Godot_properties.root_type
        collection_props.append_parent_collection = context.scene.GBGE_Godot_properties.append_parent_collection
        collection_props.asset_name = context.collection.name




classes = [
    GBGE_preferences,
    GBGE_asset_properties,
    GBGE_Godot_properties
]

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Collection.GBGE_asset_properties = bpy.props.PointerProperty(type=GBGE_asset_properties)
    bpy.types.Scene.GBGE_Godot_properties = bpy.props.PointerProperty(type=GBGE_Godot_properties)
    bpy.types.COLLECTION_PT_exporters.prepend(draw_export_collection) #This line makes it so the extra buttons get drawn on the collection export setup I havent found any documentation on COLLECTION_PT_exporters


def unregister():
    for c in classes:
        bpy.utils.unregister_class(c)
    del bpy.types.Collection.GBGE_asset_properties 
    del bpy.types.Scene.GBGE_Godot_properties 
    bpy.types.COLLECTION_PT_exporters.remove(draw_export_collection)


def draw_export_collection(self, context):
    collection = context.collection
    if not collection:
        return
    if not collection.exporters:
        return
    active_exporter = collection.exporters[collection.active_exporter_index]
    layout = self.layout

    props = context.collection.GBGE_asset_properties

    layout.prop(props, 'export_type')
    if props.export_type in ['ASSET', 'CHARACTER']:
        layout.prop(props, 'root_type')
        #layout.prop(props, 'append_parent_collection')
        layout.prop(props, 'placeholder_materials')
    #elif props.export_type=='ANIMATION':
        #layout.prop(props, 'anim_type')
    #layout.operator('gltfio.initialize_export_collection')
    layout.prop(props, 'asset_name')
    row = layout.row()
    row.enabled = False
    row.prop(props, 'asset_id')

class glTF2ExportUserExtension:
    def __init__(self):
        # We need to wait until we create the gltf2UserExtension to import the gltf2 modules
        # Otherwise, it may fail because the gltf2 may not be loaded yet
        from io_scene_gltf2.io.com.gltf2_io_extensions import Extension

        self.Extension = Extension
        self.properties = bpy.context.scene.gltfIOGodotProperties

    def pre_export_hook(self, export_settings):
        #pre_export(export_settings)

    def post_export_hook(self, export_settings):
        print('false')

        #post_export(export_settings)

