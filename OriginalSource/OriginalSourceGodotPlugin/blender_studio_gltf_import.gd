@tool
extends EditorPlugin

var DEBUG = 0

var reimport_flag = false

var gltf_post_import_plugin = preload('gltf_scene_import_post.gd').new()

var file_system_signals = {
	"filesystem_changed": _on_filesystem_changed,
	"resources_reimporting": _on_resources_reimporting,
	"resources_reimported": _on_resources_reimported,
	"resources_reload": _on_resources_reload,
	"sources_changed": _on_sources_changed,
}

func _enter_tree():
	# Initialization of the plugin goes here.
	add_scene_post_import_plugin(gltf_post_import_plugin)
	var file_system = get_editor_interface().get_resource_filesystem()
	for s in self.file_system_signals.keys():
		file_system.connect(s, self.file_system_signals[s])

func _exit_tree():
	# Clean-up of the plugin goes here.
	remove_scene_post_import_plugin(gltf_post_import_plugin)
	var file_system = get_editor_interface().get_resource_filesystem()
	for s in self.file_system_signals.keys():
		file_system.disconnect(s, self.file_system_signals[s])
	pass

func _on_filesystem_changed():
	if DEBUG >=1:
		print('FILESYSTEM CHANGED')
	pass

func _on_sources_changed(exist):
	if self.DEBUG >=1:
		print('SOURCES CHANGED')
	if self.reimport_flag:
		var filesystem = EditorInterface.get_resource_filesystem()
		reimport_recursive(filesystem.get_filesystem())
		self.reimport_flag = false
	
func reimport_recursive(dir: EditorFileSystemDirectory) -> void:
	var filesystem = EditorInterface.get_resource_filesystem()
	var path = dir.get_path()
	for i in range(dir.get_file_count()):
		var file_name = dir.get_file(i)
		if file_name.get_extension() != 'gltf':
			continue
		var file_path = path+file_name
		if FileAccess.file_exists(file_path+'.reimport'):
			DirAccess.remove_absolute(file_path+'.reimport')
			filesystem.reimport_files([file_path])
	for i in range(dir.get_subdir_count()):
		reimport_recursive(dir.get_subdir(i))

func _on_resources_reload(paths):
	if DEBUG >= 1:
		print('RELOADING '+str(paths))
	pass

func _on_resources_reimporting(paths):
	if DEBUG >= 1:
		print('REIMPORTING '+str(paths))
	
	var filesystem = EditorInterface.get_resource_filesystem()
	for path in paths:
		if not path.get_extension() == 'gltf':
			continue
		if not ResourceLoader.exists(path):
			var file = FileAccess.open(path+'.reimport', FileAccess.WRITE)
			file.store_string('')
			self.reimport_flag = true
		
		import_preparation(path)

func mark_animation_export(import_config: ConfigFile, gltf, gltf_path):
	if not 'animations' in gltf.keys():
		return
		
	if 'extras' not in gltf['scenes'][0].keys():
		return
	var extras = gltf['scenes'][0]['extras']
	if 'asset_type' not in extras.keys():
		return
	if extras['asset_type'] != 'ANIMATION':
		return
	var anim_config = {'animations': {}}
	for anim_data in gltf['animations']:
		if not anim_config:
			anim_config['animations'] = {}
	
		var res_path = gltf_path.get_base_dir().path_join(anim_data['name']+'.tres')

		anim_config['animations'][anim_data['name']] = {
					"save_to_file/enabled": true,
					"save_to_file/keep_custom_tracks": true,
					"save_to_file/path": res_path,
					"settings/loop_mode": int(extras['anim_type']=='LOOP'),
					
				}
				
				
	var optimizer_settings = {"nodes": {
		"PATH:AnimationPlayer": {
			"optimizer/enabled": false,
			"optimizer/max_angular_error": 0.1,
			"optimizer/max_velocity_error": 0.1
			}
		}
	}
		
	if anim_config:
		var subres
		if '_subresources' in import_config.get_section_keys('params'):
			subres = import_config.get_value('params', '_subresources')
			for k in anim_config.keys():
				subres[k] = anim_config[k]
		else:
			subres = anim_config
		subres['nodes'] = optimizer_settings["nodes"]
		import_config.set_value('params', '_subresources', subres)
	import_config.set_value('params', 'animation/fps', 24)
	import_config.set_value('params', 'animation/remove_immutable_tracks', false)

func mark_materials_export(import_config, gltf, gltf_path):
	if not 'materials' in gltf.keys():
		return
		
	var material_index = JSON.parse_string(FileAccess.open('res://material_index.json', FileAccess.READ).get_as_text())['assets']
	
	var mat_config = {}
	for mat in gltf['materials']:
		if 'extras' not in mat.keys():
			continue
		if 'asset_id' not in mat['extras']:
			continue
		var asset_id = mat['extras']['asset_id']
		if not mat_config:
			mat_config['materials'] = {}
			
		if asset_id not in material_index.keys():
			push_error('Did not find material '+str(asset_id)+' in material index!')
			continue
	
		var res_path = 'res://'+material_index[asset_id]['filepath']+'.tres'

		mat_config['materials'][mat['name']] = {
			"use_external/enabled": true,
			"use_external/path": res_path
		}
		
		var shader_material : Material
		if FileAccess.file_exists(res_path):
			shader_material = ResourceLoader.load(res_path)
		else:
			shader_material = ShaderMaterial.new()
		ResourceSaver.save(shader_material, res_path)
		
		
	if mat_config:
		var subres
		if '_subresources' in import_config.get_section_keys('params'):
			subres = import_config.get_value('params', '_subresources')
			for k in mat_config.keys():
				subres[k] = mat_config[k]
		else:
			subres = mat_config
		import_config.set_value('params', '_subresources', subres)

func _on_resources_reimported(paths):
	if self.DEBUG >= 1:
		print('REIMPORTED '+str(paths))
	var filesystem = EditorInterface.get_resource_filesystem()
	for path in paths:
		if not path.get_extension() == 'gltf':
			continue

func import_preparation(gltf_path: String) -> void:
	var asset_type = null
	
	var json = JSON.parse_string(FileAccess.open(gltf_path, FileAccess.READ).get_as_text())
	if 'extras' in json['scenes'][0].keys():
		var extras = json['scenes'][0]['extras']
		if 'asset_type' in extras.keys():
			asset_type = extras['asset_type']
		
	if not asset_type or asset_type in ['ASSET', 'CHARACTER']:
		var scene_path = '.'.join(gltf_path.split('.').slice(0, -1))+'.tscn'
		if not FileAccess.file_exists(scene_path):
			var filesystem = EditorInterface.get_resource_filesystem()
			filesystem.update_file(gltf_path)
			filesystem.scan_sources()
	import_config_setup(gltf_path, asset_type)

func import_config_setup(gltf_path, asset_type = null) -> void:
	
	var import_config_path = gltf_path+'.import'
	var gltf = JSON.parse_string(FileAccess.open(gltf_path, FileAccess.READ).get_as_text())
	var asset_index = JSON.parse_string(FileAccess.open('res://asset_index.json', FileAccess.READ).get_as_text())['assets']
	
	var import_config = ConfigFile.new()
	import_config.load(import_config_path)
	
	if not asset_type or asset_type in ['ANIMATION']:
		mark_animation_export(import_config, gltf, gltf_path)
		config_anim(import_config, gltf, asset_index)
	if not asset_type or asset_type in ['ASSET', 'CHARACTER']:
		mark_materials_export(import_config, gltf, gltf_path)
		config_asset(import_config, gltf, asset_index)
	
	import_config.save(import_config_path)

func config_anim(import_config: ConfigFile, gltf: Dictionary, asset_index: Dictionary) -> void:
	if not 'params' in import_config.get_section_keys('params'):
		return
	var subres = import_config.get_value('params', '_subresources', null)
	if not subres:
		return
	if 'animations' not in subres.keys():
		return
	
	for anim_name in subres['animations'].keys():
		# fetch animation library
		var ref_asset_id = gltf['scenes'][0]['extras']['ref_asset_id']
		var char_info = asset_index[ref_asset_id]
		var char_name = char_info['name']
		var char_path = 'res://'.path_join(char_info['filepath'])
		
		var anim_lib = null
		var anim_lib_path = char_path.get_base_dir().path_join(char_name+'-anim_lib.tres')

		if ResourceLoader.exists(anim_lib_path):
			anim_lib = load(anim_lib_path)
		else:
			anim_lib = AnimationLibrary.new()
			anim_lib.resource_path = anim_lib_path
			anim_lib.resource_name = char_name+' Animation Library'
			
		var anim = load(subres['animations'][anim_name]['save_to_file/path'])
		
		if not anim:
			push_warning('Could not find animation resource at '+subres['animations'][anim_name]['save_to_file/path'])
		anim_lib.add_animation(anim.resource_name, anim)
		
		ResourceSaver.save(anim_lib)

func config_root_type(import_config: ConfigFile, extras: Dictionary) -> void:
	var root_type = null
	
	if not 'root_type' in extras.keys():
		return
	root_type = extras['root_type']
	if not root_type:
		return
	
	var root_type_map = {
		'NONE': 'Node3D',
		'STATIC': 'StaticBody3D',
		'PASS_THROUGH': 'Area3D',
	}
	
	import_config.set_value('params', 'nodes/root_type', root_type_map[root_type])

func config_asset(import_config: ConfigFile, gltf: Dictionary, asset_index: Dictionary) -> void:
	if 'extras' not in gltf['scenes'][0].keys():
		return
	var extras = gltf['scenes'][0]['extras']
	
	config_root_type(import_config, extras)
