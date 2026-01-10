@tool # Needed so it runs in editor.
extends EditorScenePostImport

var DEBUG = 0

func _post_import(scene: Node) -> Object:
	if self.DEBUG >=1:
		print('IMPORT SCRIPT RUNNING: '+str(scene))
	var gltf_path = self.get_source_file()
	
	if not ResourceLoader.exists(gltf_path):
		var filesystem = EditorInterface.get_resource_filesystem()
		filesystem.update_file(gltf_path)
		filesystem.scan_sources()
		print("Initializing import ("+gltf_path+")")
		return scene
	
	var msg = 'IMPORT: '+scene.name+' from '+gltf_path
	var asset_type = null
	
	# TODO replace json parsing by integrate meta lookup
	var json = JSON.parse_string(FileAccess.open(gltf_path, FileAccess.READ).get_as_text())
	if 'extras' in json['scenes'][0].keys():
		var extras = json['scenes'][0]['extras']
		if 'asset_type' in extras.keys():
			asset_type = extras['asset_type']
			msg += ' as ' + asset_type
			
	print()
	print(msg)
		
	if not asset_type or asset_type in ['ASSET', 'CHARACTER']:
		process_collision_nodes(scene, scene)
		process_visibility_nodes(scene)
		process_leash_collision_points(scene)
		deferred_asset_import(scene)
	if not asset_type or asset_type in ['ANIMATION']:
		pass
	
	scene.name += '-IMPORT'
	return scene

func ensure_scene_for_gltf(gltf_path: String) -> Node:
	if self.DEBUG >=1:
		print('ENSURING SCENE FILE: '+gltf_path)
	var scene_path = '.'.join(gltf_path.split('.').slice(0, -1))+'.tscn'
	
	if FileAccess.file_exists(scene_path):
		print('FOUND '+scene_path)
		var scene = load(scene_path)
		if not scene:
			push_error("Could not instantiate scene '"+str(scene_path)+"'")
			return null
		return load(scene_path).instantiate()
	
	var packed_scene = PackedScene.new()
	var gltf_node = Node3D.new()
	var gltf_instance = null
	gltf_instance = ResourceLoader.load(gltf_path, 'Scene').instantiate()
	if not gltf_instance:
		push_error("Didn't find .gltf when creating .tscn")
	gltf_node.add_child(gltf_instance)
	gltf_instance.owner = gltf_node
	gltf_node.name = gltf_path.get_file().get_basename()
	var result = packed_scene.pack(gltf_node)
	if result == OK:
		print('SAVING '+scene_path)
		var error = ResourceSaver.save(packed_scene, scene_path)
		if error != OK:
			push_error("An error occurred while saving the scene to disk.")
	return load(scene_path).instantiate()

func deferred_asset_import(scene: Node) -> void:
	if self.DEBUG >=1:
		print('DEFERRED ASSET IMPORT: '+str(scene))
	var gltf_path = self.get_source_file()
		
	ensure_scene_for_gltf(gltf_path)
	
	var json = JSON.parse_string(FileAccess.open('res://asset_index.json', FileAccess.READ).get_as_text())
	
	process_node_instancing(scene, scene, json['assets'])

func process_node_instancing(node: Node, scene: Node, asset_lib: Dictionary) -> void:
	process_instancing_node(node, scene, asset_lib)
	
	for n in node.get_children():
		process_node_instancing(n, scene, asset_lib)

func process_instancing_node(node: Node, scene: Node, asset_lib: Dictionary) -> void:
	if self.DEBUG >=1:
		print('PROCESS INSTANCING: '+str(node))
	if not node.has_meta('extras'):
		return
	var extras = node.get_meta('extras')
	if 'instance_asset_id' not in extras.keys():
		return
	var asset_id = extras['instance_asset_id']
	if asset_id not in asset_lib.keys():
		push_error('Could not find asset info for '+str(asset_id))
		return
	var asset_info = asset_lib[asset_id]
	var gltf_path = 'res://'+asset_info['filepath']
	var scene_path = '.'.join(gltf_path.split('.').slice(0, -1))+'.tscn'
	print('Instantiating '+asset_info['name']+'('+asset_id+')'+' on '+node.name+' asset')
	var scene_instance = ensure_scene_for_gltf(gltf_path)
	if not scene_instance:
		print('import issue reimport')
		return
	node.add_sibling(scene_instance)
	scene_instance.transform = node.transform
	scene_instance.owner = node.get_parent()
	var name = node.name
	node.name = 'DELETE'
	node.queue_free()
	scene_instance.name = name
	print('CREATED INSTANCE')

func process_visibility_nodes(node: Node3D) -> void:
	for n in node.get_children():
		process_visibility_nodes(n)
	
	if not node.get_class() == 'MeshInstance3D':
		return
	if not node.has_meta('extras'):
		return
	var extras = node.get_meta('extras')
	if not extras:
		return
	if not 'visibility_info' in extras.keys():
		return
	var visibility_info = null
	if 'visibility_info' in extras.keys():
		visibility_info = extras['visibility_info']
	
	if 'shadow' in visibility_info.keys():
		node.cast_shadow = visibility_info['shadow']
	else:
		# restore defaults
		node.cast_shadow = true

func process_collision_nodes(node: Node3D, scene: Node, transform: Transform3D = Transform3D.IDENTITY) -> void:
	for n in node.get_children():
		process_collision_nodes(n, scene, transform * node.transform)
		
	if not node.has_meta('extras'):
		return
	var extras = node.get_meta('extras')
	if not extras:
		return
	if not 'collision_info' in extras.keys():
		return
	var collision_info = null
	if 'collision_info' in extras.keys():
		collision_info = extras['collision_info']
	var global_transform = transform * node.transform
	node.reparent(scene, false)
	node.transform = global_transform
	node.owner = scene
	if collision_info['type'] == 'MESH':
		collision_mesh_conversion(node, collision_info)
	elif collision_info['type'] == 'PRIMITIVE':
		collision_primitive(node, collision_info)
			
func process_leash_collision_points(scene: Node3D):
	for node in scene.get_children():
		if node.name.contains("HLP-leash_point"):
			node.add_to_group("LeashPivots", true)

func collision_primitive(node : Node3D, collision_info : Dictionary) -> void:
	var new_collision_shape = CollisionShape3D.new()
	
	var original_name = node.name
	node.name = 'DELETE'
	
	node.add_sibling(new_collision_shape)
	new_collision_shape.set_owner(node.get_parent())
	new_collision_shape.name = original_name
	new_collision_shape.position = node.position
	new_collision_shape.scale = node.scale
	new_collision_shape.rotation = node.rotation
	
	var primitive_shape = null
	if collision_info['shape'] == 0:
		primitive_shape = SphereShape3D.new()
	elif collision_info['shape'] == 1:
		primitive_shape = BoxShape3D.new()
	elif collision_info['shape'] == 2:
		primitive_shape = CapsuleShape3D.new()
	elif collision_info['shape'] == 3:
		primitive_shape = CylinderShape3D.new()
	
	if 'radius' in primitive_shape:
		primitive_shape.radius = collision_info['radius']
	if 'height' in primitive_shape:
		primitive_shape.height = collision_info['height']
	if 'size' in primitive_shape:
		primitive_shape.size.x = collision_info['size'][0]
		primitive_shape.size.y = collision_info['size'][2]
		primitive_shape.size.z = collision_info['size'][1]
	
	new_collision_shape.shape = primitive_shape
	
	# Delete nodes
	node.queue_free()
	
func collision_mesh_conversion(node : MeshInstance3D, collision_info : Dictionary) -> void:
	print("Converting to trimesh")
	
	# Create the new collision shape
	var concave = true
	if collision_info:
		concave = collision_info['concave']
	if concave:
		node.create_trimesh_collision()
	else:
		node.create_convex_collision(true, true)
	
	var original_name = node.name
	var static_body = node.get_child(0)
	var collision_shape = static_body.get_child(0)
	var trimesh_shape = collision_shape.shape.duplicate()
	
	# Rename so there's no name conflict
	node.name = "delete"
	var new_collision_shape = CollisionShape3D.new()
	new_collision_shape.shape = trimesh_shape
	new_collision_shape.name = original_name
	new_collision_shape.position = node.position
	new_collision_shape.scale = node.scale
	new_collision_shape.rotation = node.rotation
	node.add_sibling(new_collision_shape)
	# Setting the owner is vital. Otherwise it won't show up
	new_collision_shape.set_owner(node.get_parent())
	# Delete nodes
	collision_shape.queue_free()
	static_body.queue_free()
	node.queue_free()
