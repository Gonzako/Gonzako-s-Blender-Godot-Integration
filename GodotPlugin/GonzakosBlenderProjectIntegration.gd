@tool
extends EditorPlugin

var DEBUG = true

var reimport_flag = false

var scene_import_post = preload('GonzakoBlenderIntegrationPost.gd').new()

var file_system_signals = {
	"filesystem_changed": _on_filesystem_changed,
	"resources_reimporting": _on_resources_reimporting,
	"resources_reimported": _on_resources_reimported,
	"resources_reload": _on_resources_reload,
	"sources_changed": _on_sources_changed,
}


func _enter_tree() -> void:
	# Initialization of the plugin goes here.
	add_scene_post_import_plugin(scene_import_post)
	var file_system = get_editor_interface().get_resource_filesystem()
	for file_signal in self.file_system_signals.keys():
		file_system.connect(file_signal, self.file_system_signals[file_signal])
	pass


func _exit_tree() -> void:
	# Clean-up of the plugin goes here.
	remove_scene_post_import_plugin(scene_import_post)
	var file_system = get_editor_interface().get_resource_filesystem()
	for file_signal in self.file_system_signals.keys():
		file_system.disconnect(file_signal, self.file_system_signals[file_signal])
	pass

func _on_filesystem_changed() -> void:
	if self.DEBUG:
		print('FILESYSTEM CHANGED')
	pass

func _on_resources_reimporting(paths) -> void:
	if self.DEBUG:
		print('REIMPORTING '+str(paths))
	pass

func  _on_resources_reimported(paths) -> void:
	pass

func  _on_resources_reload(paths) -> void:
	if self.DEBUG:
		print('RELOADING '+str(paths))
	pass

func _on_sources_changed(exist) -> void:
	if self.DEBUG:
		print('SOURCES CHANGED')
	if self.reinport_flag:
		var filesystem = EditorInterface.get_resource_filesystem()
		#reimport_recursive(fylesystem.get_filesystem())
		self.reimport_flag = false
	pass
