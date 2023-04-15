""" Blender addon for converting and exporting Blender objects to an SVG file """

# Metadata
__author__ = "Craszh"
__license__ = "GNU GPL v3.0"
__version__ = "2.0"
__date__ = "20. 03. 2023"

# Blender addon metadata
bl_info = {
    "name" : "Export SVG",
    "description" : "Converts MESH, CURVE, GPENCIL and FONT objects to vector graphics with selected attributes and exports it as an SVG file",
    "author" : "Craszh",
    "version" : (2, 0),
    "blender" : (3,2,0),
    "location" : "View3D > Sidebar > Export SVG",
    "url": "https://github.com/Craszh/BlenderModelToSVG",
    "wiki_url": "https://github.com/Craszh/BlenderModelToSVG",
    "category" : "Import-Export",
}

# Imports
from cmath import inf
from math import pow
from copy import deepcopy
from datetime import datetime
from collections import deque
from abc import ABC, abstractmethod
import xml.etree.ElementTree as ET
import numpy
import bpy
import bmesh
import functools
from mathutils.geometry import distance_point_to_plane
from mathutils.geometry import intersect_line_plane
from mathutils.geometry import normal as get_normal
from mathutils import Vector
from mathutils import Matrix
from bpy_extras import view3d_utils
from bpy_extras import object_utils
import traceback

#
# Global settings
#

VERT_DECIMALS = 5
PLANE_DISTANCE_THRESHOLD = 0.001
POLYGON_CULL_THRESHOLD = 1E-6
POLYGON_CUT_PRECISION = 1000.0

MATERIAL_PREFIX = "bl_mat_"
RENAMED_MATERIAL_PREFIX = "bl_matrenamed_"
ANNOTATION_PREFIX = "bl_ann_"
RENAMED_ANNOTATION_PREFIX = "bl_annrenamed_"
CAMERA_PREFIX = "bl_cam_"
RENAMED_CAMERA_PREFIX = "bl_camrenamed_"
COLLECTION_PREFIX = "bl_coll_"
RENAMED_COLLECTION_PREFIX = "bl_collrenamed_"
ANIMATION_PREFIX ="anim_"

runtime_error_dict = {
    1: "Output directory not found",
    2: "Permission to open file denied",
    3: "BSP cycles limit reached, scene is too complex for the currently set limit",
    4: "Export interrupted",
    5: "OS error occured",
    6: "Unexpected error occured",
}

STARTTIME = datetime.now()

#
# Misc methods
#

def get_object_list(context):
    """Gets a list of objects to be used in conversion

    :param context: Context
    :type context: bpy.context
    :return: List of objects to be used during the conversion process
    :rtype: List of bpy.types.Object
    """
    sel_method = EnumPropertyDictionaries.selection\
        [context.scene.export_properties.selection_method]
    coll = context.scene.export_properties.selected_collection

    object_list = []
            
    if sel_method == 0:
        object_list = context.selected_objects
    elif sel_method == 1:
        if coll is not None:
            for obj in coll.all_objects:
                object_list.append(obj)
    elif sel_method == 2:
        if coll is not None:
            for obj in coll.all_objects:
                object_list.append(obj)
        object_list = list(set(object_list) & set(context.visible_objects))
    elif sel_method == 3:
        for obj in context.scene.objects:
            object_list.append(obj)
    else:
        for obj in context.visible_objects:
            object_list.append(obj)

    return object_list

def display_message(message_lines, message_title, message_icon):
    """Method for displaying a message to the user on screen

    :param message_lines: Text body of the message
    :type message_lines: [string]
    :param message_title: Title of the message
    :type message_title: string
    :param message_icon: Icon of the message
    :type message_icon: string
    """
    def draw(self, context):
        for line in message_lines:
            self.layout.label(text = line)

    bpy.context.window_manager.popup_menu(draw, title = message_title, icon = message_icon)

""" Currently unused
def copy_images(object_list, output_path):
    Method for copying source files of all selected images into the output folder

    :param object_list: List of objects used in the conversion process
    :type object_list: List of bpy.types.Object
    :param output_path: Path to the output file
    :type output_path: str
    
    # Gets absolute paths of all used images
    files_to_copy = []
    for obj in object_list:
        if obj.type == "EMPTY" and type(obj.data) == bpy.types.Image:
            path = bpy.path.abspath(obj.data.filepath)
            if path[-4:] != ".png" and path[-4:] != ".jpg" and path[-5:] != ".jpeg":
                continue
            if obj.data.source != "FILE" or obj.data.size[0] <= 0 or obj.data.size[1] <= 0:
                continue
            files_to_copy.append(path)

    base_path = output_path[0:-4]
    files_to_copy = set(files_to_copy)

    # Copies all used images into the output directory
    for original_path in files_to_copy:
        image_name = basename(original_path)
        new_path = base_path + "_" + image_name
        #print("Copying from ", original_path, new_path)
        copyfile(original_path, new_path)"""

def check_valid_css_name(mat_name):
    """Checks if name is a valid css identifier

    :param mat_name: Name to check
    :type mat_name: str
    :return: True if valid, False otherwise
    :rtype: bool
    """
    for char in mat_name:
        if char != '-' and char != '_' and (not char.isalnum()):
            return False

    return True

def check_valid_file_name(mat_name):
    """Checks if name is a valid file name

    :param mat_name: Name to check
    :type mat_name: str
    :return: True if valid, False otherwise
    :rtype: bool
    """
    for char in mat_name:
        if char != '-' and char != '_' and (not char.isalnum()) and char != ".":
            return False

    return True

def check_valid_pattern(pattern):
    """Checks if a string is a valid <pattern> element

    :param pattern: String containing pattern
    :type pattern: str
    :return: True if valid, False otherwise
    :rtype: bool
    """
    # Finds pattern by looking for the first element with tag ending in "pattern"
    try:
        xml = ET.fromstring(pattern)
        for child in xml.iter():
            tag = child.tag
            if len(tag) >= 7 and tag[-7:] == "pattern":
                pattern = child
                break
        if pattern is None:
            raise ValueError("Pattern not found")
    except:
        return False
    return True

def get_rgb_val(c):
    """Converts color from Blender (nonlinear) COLOR_GAMMA value to real RGB value

    :param c: Color value (0.0-1.0)
    :type c: float
    :return: Real RGB value of the color (0-255)
    :rtype: int
    """
    return (max(min(int(c * 255 + 0.5), 255), 0))

# Source: https://blender.stackexchange.com/questions/260956/convert-rgb-256-to-rgb-float/260961
def get_rgb_val_from_linear(c):
    """Converts color from Blender (linear) COLOR value to real RGB value

    :param c: Color value (0.0-1.0)
    :type c: float
    :return: Real RGB value of the color (0-255)
    :rtype: int
    """
    color = max(0.0, c * 12.92) if c < 0.0031308 else 1.055 * pow(c, 1.0 / 2.4) - 0.055
    return (max(min(int(color * 255 + 0.5), 255), 0))

#
# PROPERTIES
#

class EnumPropertyDictionaries:
    """Class containing dictionaries for translating enum properties into integers
    """
    cutting = {
        "cut.bsp": 0
    }

    polygon_sorting = {
        "heuristic.bbmin": 0,
        "heuristic.bbmid": 1,
        "heuristic.bbmax" : 2,
        "heuristic.weightmid" : 3
    }

    light_source = {
        "light.point" : 0,
        "light.planar" : 1
    }

    camera = {
        "camera.view" : 0,
        "camera.obj" : 1
    }

    global_sorting = {
        "sorting.bbmin" : 0,
        "sorting.bbmax" : 1,
        "sorting.bbmid" : 2,
    }

    collection_sorting = {
        "coll.bbmin" : 0,
        "coll.bbmax" : 1,
        "coll.bbmid" : 2,
        "coll.hier" : 3
    }

    text_options = {
        "text.raw" : 0,
        "text.curve_norot" : 1,
        "text.curve_rotate" : 2,
        "text.mesh_norot" : 3,
        "text.mesh_rotate" : 4
    }

    selection = {
        "sel.sel" : 0,
        "sel.col" : 1,
        "sel.cov" : 2,
        "sel.all" : 3, 
        "sel.alv" : 4,
    }

    modifiers = {
        "mod.nomod" : 0,
        "mod.active" :  1,
    }

    """
    timing_function = {
        "timing.ease" : 0,
        "timing.linear" : 1,
        "timing.easein" : 2,
        "timing.easeout" : 3,
        "timing.easeinout" : 4,
    }"""
    """
    animation_direction = {
        "dir.normal" : 0,
        "dir.reverse" : 1,
        "dir.alt" : 2,
        "dir.revalt" : 3,
    }"""
    """
    animation_fill_mode = {
        "fill.none" : 0,
        "fill.forwards" : 1,
        "fill.backwards" : 2,
        "fill.both" : 3,
    }"""

class ExportSVGProperties(bpy.types.PropertyGroup):
    
    cutting_options = [
        ("cut.bsp", "BSP Tree",
         "Partitions and sorts the scene using a BSP tree. WARNING: Be careful when setting"\
            " the maximum cycle limit", "ERROR", 0),
    ]

    polygon_sorting_options = [
        ("heuristic.bbmin", "Closest Vertex",
         "Sorts polygons based on the depth of their closest vertex", "", 0),
        ("heuristic.bbmid", "Center",
         "Sorts polygons based on the depth of their center", "", 1),
        ("heuristic.bbmax", "Furthest Vertex",
         "Sorts polygons based on the depth of their furthest vertex", "", 2),
        ("heuristic.weightmid", "Weighted Center",
         "Sorts polygons based on the average depth of all vertices", "", 3)
    ]

    light_source_options = [
        ("light.point", "Point Light", 
        "Use a single 3D point in the scene as the light source", "", 0),
        ("light.planar", "Planar Light",
        "Use a selected light direction", "", 1)
    ]

    camera_options = [
        ("camera.view", "Viewport Camera", 
        "Use the current 3D viewport camera as the single camera for the scene", "", 0),
        ("camera.obj", "Camera Object(s)",
        "Allows the selection of (multiple) cameras in the scene that can be used for "\
        "exporting (multiple) svg files from their respective views. "\
        "One .svg file will be created per each selected camera, named <PATH>_<CAMERA_NAME>.svg",
        "", 1)
    ]

    """filling_options = [
        ("fill.color", "Color/Lighting",
         "Fill elements with a set color (that can be affected by lighting for MESH types)",
         "", 0),
        ("fill.pattern", "Custom Pattern",
         "Fill elements with a custom pattern", "", 1),
        ("fill.image", "Image",
         "Fill elements with a background image", "", 2),
    ]"""

    global_sorting_options = [
        ("sorting.bbmin", "Closest Point",
         "Sorts elements based on the minimum depth of their bounding box", "", 0),
        ("sorting.bbmax", "Furthest Point",
         "Sorts elements based on the maximum depth of their bounding box", "", 1),
        ("sorting.bbmid", "Middle Point",
         "Sorts elements based on the depth of the center of their bounding box", "", 2),
    ]

    collection_sorting_options = [
        ("coll.bbmin", "Closest Point",
         "Sorts collections based on the minimum depth of their bounding box", "", 0),
        ("coll.bbmax", "Furthest Point",
         "Sorts collections based on the maximum depth of their bounding box", "", 1),
        ("coll.bbmid", "Middle Point",
         "Sorts collections based on the depth of the center of their bounding box", "", 2),
        ("coll.hier", "Object List Order",
         "Sorts collections based on their first appearance in the list of objects (meaning collection "\
         "that is placed on the bottom of the list is rendered first, therefore appearing behind the "\
         "collections that are above it in the list, similarly to how layers work in a 2D editor)"  , "", 3)
    ]

    text_options = [
        ("text.raw", "Export As <text>",
         "Converts 3D text into SVG <text> elements with only basic formatting " + \
         "(does not look like the original shape, only raw text is kept)", "", 0),
        ("text.curve_norot", "Export As <path>",
         "Converts the text into curves before exporting to SVG <path> elements. " + \
         "This option will keep the closest resemblance to the original, but the resulting " + \
         "SVG will contain curves instead of text elements", "", 1),
        ("text.curve_rotate", "Face Camera And Export As <path>",
         "Same as Export as <path> but text will be rotated to face the camera", "", 2),
        ("text.mesh_norot", "Export As <polygon>",
         "Converts the text into mesh before exporting to SVG <polygon> elements. " + \
         "Similar to <path> options, but the SVG will contain polygons instead of curves " + \
         "to represent the text. WARNING: This results in many polygons being generated even for a short text", "ERROR", 3),
        ("text.mesh_rotate", "Face Camera And Export As <polygon>",
         "Same as Export as <polygon> but text will be rotated to face the camera. WARNING: This results in many polygons being generated even for a short text", "ERROR", 4) 
    ]

    selection_options = [
        ("sel.sel", "Selected Objects",
         "Only objects currently in selection will be exported", "", 0),
        ("sel.col", "Collection",
         "Only objects (and collections) belonging to a selected collection will be exported", "", 1),
        ("sel.cov", "Collection Visible Objects",
         "Only visible objects (and collections) belonging to a selected collection that have not been 'Hidden in Viewport' in the outliner will be exported", "", 2),
        ("sel.all", "All Objects",
         "All objects in the scene will be exported. WARNING: Be careful when a scene has many objects", "ERROR", 3), 
        ("sel.alv", "All Visible Objects",
         "All visible objects that have not been 'Hidden in Viewport' in the outliner will be used in the conversion. WARNING: Be careful when a scene has many objects", "ERROR", 4),
    ]

    modifiers_options = [
        ("mod.nomod", "Disable",
         "Converts non-evaluated objects", "", 0),
        ("mod.active", "Enable",
         "Converts evaluated objects (modifiers only work with MESH and GPENCIL objects)", "", 1),
    ]

    # Stores the text override option
    polygon_override: bpy.props.BoolProperty(
        name = "Override individual material settings",
        description = "If checked, the settings below will be used for every MESH type object, "\
            "regardless of their individually assigned materials. If not checked, the settings "\
            "of an object's material will take priority (if it has a material assigned)",
        default = False
    )

    # Stores the stroke width value
    polygon_stroke_width: bpy.props.FloatProperty(
        name = "Polygon stroke width",
        description = "Stroke width of polygons (thick strokes can create artifacts near sharp edges of objects "\
            " and thin strokes can create visible gaps between adjoined polygons)",
        default = 0.35,
        min = 0.0,
        #max = 3.0,
        soft_min = 0.0,
        #soft_max = 3.0
    )

     # Stores the same stroke color as fill color option
    polygon_stroke_same_as_fill: bpy.props.BoolProperty(
        name = "Set stroke color to the same color as fill",
        description = "If not checked, allows setting custom color of polygon strokes. " + \
                      "If checked, the color of strokes will be the same as the polygon's final fill color "\
                      "(meaning there will be no visible strokes even when polygon's fill color changes due to lighting)",
        default = False
    )

    # Stores the stroke color option
    polygon_stroke_color: bpy.props.FloatVectorProperty(
        name = "Stroke color and opacity",
        description = "Color and opacity of polygon strokes",
        min = 0.0,
        max = 1.0,
        default = [0.0, 0.0, 0.0, 1.0],
        size = 4,
        subtype = "COLOR_GAMMA"
    )

    # Stores the dashed stroke option
    polygon_dashed_stroke: bpy.props.BoolProperty(
        name = "Dashed stroke",
        description = "Toggles the option for a dashed polygon stroke",
        default = False
    )

    # Stores the polygon dash array
    polygon_dash_array: bpy.props.FloatVectorProperty(
        name = "Polygon stroke dash array",
        description = "Array for polygon dash parameters (0 fields are ignored)",
        default = [2, 0, 0, 0],
        min = 0.0,
        #max = 100.0,
        size = 4,
        precision = 2,
    )

    # Stores the custom fill option
    polygon_disable_lighting: bpy.props.BoolProperty(
        name = "Disables lighting",
        description = "If checked disables lighting and uses a set Fill Color or Pattern String to fill the polygons. "\
                      "If not checked, uses set Fill Color as a base/diffuse color when calculating lighting",
        default = False
    )

    def set_use_pattern(self, context):
        if self.polygon_use_pattern == True:
            self.polygon_disable_lighting = True


    # Stores the use pattern option
    polygon_use_pattern: bpy.props.BoolProperty(
        name = "Use fill pattern",
        description = "Use svg <pattern> to fill polygons. WARNING: Patterns work when displaying the SVG in web browser "\
                      "but can't be displayed for example in a 2D graphics editor like Inkscape",
        default = False,
        update = set_use_pattern
    )

    # Stores the selected pattern
    polygon_custom_pattern: bpy.props.StringProperty(
        name= "Custom pattern",
        description = "Correctly formatted SVG containing <pattern> that will be copied to the output file and assigned to polygons. "\
            "Error warning will be displayed if the SVG format is incorrect or <pattern> element is missing",
        default = ""
    )

    # Stores the polygonfill color values
    polygon_fill_color: bpy.props.FloatVectorProperty(
        name = "Polygon fill color and opacity",
        description = "Color and opacity of polygon object fills (set 0 opacity for no fill)",
        min = 0.0,
        max = 1.0,
        default = [0.5, 0.5, 0.5, 1.0],
        size = 4,
        subtype = "COLOR_GAMMA"
    )

    # Stores the backface culling option
    backface_culling: bpy.props.BoolProperty(
        name = "Backface culling",
        description = "Ignores polygons that are not facing the camera"
    )

    # Stores the quick depth sort option
    cut_conflicts: bpy.props.BoolProperty(
        name = "Cut conflicting faces",
        description = "WARNING: Much slower exporting and larger file size, " \
            "however intersecting and overlapping polygons are displayed a bit more precisely. " \
            "Use only when necessary, usually only simple sorting without cutting should suffice",
    )

     # Stores the cutting algorithm option
    cutting_algorithm: bpy.props.EnumProperty(
        items = cutting_options,
        description = "Defines what algorithm is used for dealing with conflicting/intersecting polygons",
        default = "cut.bsp",
        name = "Cutting"
    )

    # Stores the sorting heuristic option for polygons
    polygon_sorting_heuristic: bpy.props.EnumProperty(
        items = polygon_sorting_options,
        description = "Defines what rule is used for sorting polygons among each other",
        default = "heuristic.bbmid",
        name = "Sorting"
    )

    # Stores the maximum BSP partition cycles option
    partition_cycles_limit: bpy.props.IntProperty(
        name = "BSP cycles limit",
        description = "Maximum number of BSP partition cyles, if the BSP tree reaches " + \
            "this depth, the conversion process is stopped. " + \
            "Higher limit allows the conversion of larger scenes, however " + \
            "it consumes much more memory and takes longer, therefore be careful when " + \
            "increasing it. It is also recommended to have the Blender console window " + \
            "ready to keyboard interrupt the process if necessary. Default limit is 500 cycles",
        default = 500,
        min = 5,
        max = 1000,
        soft_min = 5,
        soft_max = 1000
    )

    # Stores the light source option
    light_type: bpy.props.EnumProperty(
        items = light_source_options,
        description = "Defines which type of light source is used for calculating lighting",
        default = "light.point",
        name = "Light source"
    )

    # Stores the camera light option
    camera_light: bpy.props.BoolProperty(
        name = "Use point of view as light source",
        description = "Current point of view will be used as the main light source instead of an object",
        default = True
    )

    # Stores the selected point light option
    selected_point_light: bpy.props.PointerProperty(
        name = "Point Light",
        type = bpy.types.Object,
        description = "Position of this object will be used as the point light source location"
    )

    # Stores the planar light direction
    light_direction: bpy.props.FloatVectorProperty(
        name = "",
        description = "Specifies the angle under which light reaches the surface of the object",
        default = [-0.303644, 0.259109, 0.916877],
        subtype = "DIRECTION",
    )

    # Stores the grayscale option
    grayscale: bpy.props.BoolProperty(
        name = "Grayscale",
        description = "If checked, grayscale filter will be applied to the resulting image"
    )

    # Stores the light color values
    light_color: bpy.props.FloatVectorProperty(
        name = "Light color",
        description = "Color of the light emitted by the light source",
        min = 0.0,
        max = 1.0,
        default = [1.0, 1.0, 1.0],
        subtype = "COLOR_GAMMA"
    )

    # Stores the ambient light color values
    ambient_color: bpy.props.FloatVectorProperty(
        name = "Ambient color",
        description = "Color of the ambient light in the scene",
        min = 0.0,
        max = 1.0,
        default = [0.05, 0.05, 0.05],
        subtype = "COLOR_GAMMA"
    )

    # Stores the text override option
    curve_override: bpy.props.BoolProperty(
        name = "Override individual material settings",
        description = "If checked, the settings below will be used for every CURVE/GPENCIL type object, "\
            "regardless of their individually assigned materials. If not checked, the settings "\
            "of an object's material will take priority (if it has a material assigned)",
        default = False
    )

    # Stores the curve stroke width value
    curve_stroke_width: bpy.props.FloatProperty(
        name = "Curve stroke width",
        description = "Stroke width of curves",
        default = 1.0,
        min = 0.0,
        #max = 3.0,
        soft_min = 0.0,
        #soft_max = 3.0
    )

    # Stores the curve stroke color values
    curve_stroke_color: bpy.props.FloatVectorProperty(
        name = "Curve stroke color and opacity",
        description = "Color and opacity of curve strokes",
        min = 0.0,
        max = 1.0,
        default = [0.0, 0.0, 0.0, 1.0],
        size = 4,
        subtype = "COLOR_GAMMA"
    )

    # Stores the dashed stroke option
    curve_dashed_stroke: bpy.props.BoolProperty(
        name = "Dashed stroke",
        description = "Toggles the option for a dashed curve stroke",
    )

    # Stores the curve dash array
    curve_dash_array: bpy.props.FloatVectorProperty(
        name = "Curve dash array",
        description = "Array for curve dash parameters (0 fields are ignored)",
        default = [2, 0, 0, 0],
        min = 0.0,
        #max = 100.0,
        size = 4,
        precision = 2,
    )

    # Stores the use pattern option
    curve_use_pattern: bpy.props.BoolProperty(
        name = "Use fill pattern",
        description = "Use svg <pattern> to fill curves. WARNING: Patterns work when displaying the SVG in web browser "\
                      "but can't be displayed for example in a 2D graphics editor like Inkscape",
        default = False
    )

    # Stores the selected pattern
    curve_custom_pattern: bpy.props.StringProperty(
        name= "Custom pattern",
        description = "Correctly formatted SVG containing <pattern> that will be copied to the output file and assigned to curves. "\
            "Error warning will be displayed if the SVG format is incorrect or <pattern> element is missing",
        default = ""
    )

    # Stores the curve fill color values
    curve_fill_color: bpy.props.FloatVectorProperty(
        name = "Curve fill color and opacity",
        description = "Color and opacity of curve object fills (set 0 opacity for no fill)",
        min = 0.0,
        max = 1.0,
        default = [0.0, 0.0, 0.0, 0.0],
        size = 4,
        subtype = "COLOR_GAMMA"
    )

    # Stores the curve fill rule evenodd option
    curve_fill_evenodd: bpy.props.BoolProperty(
        name = "Fill rule evenodd",
        description = "If checked, sets the svg fill-rule attribute to 'evenodd'. "\
            "If not checked, default svg fill-rule is used ('nonzero')",
        default = False
    )

    # Stores the curve merge splines option
    curve_merge_splines: bpy.props.BoolProperty(
        name = "Merge splines",
        description = "If checked, all splines of a curve object "\
            "are converted into a single <path> element which results in only the area between them being filled. "\
            "This allows creating empty spaces inside the curve's area, such as the empty space in letter 'A'. "\
            "If not checked, all splines of a curve object are treated as separate curves and each "\
            "spline is converted into its own <path> element ",
        default = False
    )

    # Stores the curve merge splines option
    curve_convert_annotations: bpy.props.BoolProperty(
        name = "Convert annotations",
        description = "If checked, annotations will be converted into <path> elements as well. "\
            "If not checked, annotations are ignored. WARNING: Visual attributes of annotations are not "\
            "affected by the settings above, instead they are the same as their actual appearance in Blender",
        default = False
    )

    # Stores the text override option
    text_override: bpy.props.BoolProperty(
        name = "Override individual material settings",
        description = "If checked, the settings below will be used for every FONT type object, "\
            "regardless of their individually assigned materials. If not checked, the settings "\
            "of an object's material will take priority (if it has a material assigned)",
        default = False
    )

    # Stores the text stroke width value
    text_stroke_width: bpy.props.FloatProperty(
        name = "Text stroke width",
        description = "Stroke width of text outlines",
        default = 1.0,
        min = 0.0,
        #max = 3.0,
        soft_min = 0.0,
        #soft_max = 3.0
    )

    # Stores the text curve/polygon stroke color
    text_stroke_color: bpy.props.FloatVectorProperty(
        name = "Text stroke color and opacity",
        description = "Color and opacity of text object strokes (set 0 opacity for no strokes)",
        min = 0.0,
        max = 1.0,
        default = [0.0, 0.0, 0.0, 1.0],
        size = 4,
        subtype = "COLOR_GAMMA"
    )

    # Stores the dashed stroke option
    text_dashed_stroke: bpy.props.BoolProperty(
        name = "Text dashed stroke",
        description = "Toggles the option for a dashed stroke",
    )

    # Stores the curve dash array
    text_dash_array: bpy.props.FloatVectorProperty(
        name = "Text dash array",
        description = "Array for text stroke dash parameters (0 fields are ignored)",
        default = [2, 0, 0, 0],
        min = 0.0,
        #max = 100.0,
        size = 4,
        precision = 2,
    )

    # Stores the use pattern option
    text_use_pattern: bpy.props.BoolProperty(
        name = "Use fill pattern",
        description = "Use svg <pattern> to fill text. WARNING: Patterns work when displaying the SVG in web browser "\
                      "but can't be displayed for example in a 2D graphics editor like Inkscape",
        default = False
    )

    # Stores the selected pattern
    text_custom_pattern: bpy.props.StringProperty(
        name= "Custom pattern",
        description = "Correctly formatted SVG containing <pattern> that will be copied to the output file and assigned to text. "\
                      "Error warning will be displayed if the SVG format is incorrect or <pattern> element is missing",
        default = ""
    )

    # Stores the text curve/polygon fill color
    text_fill_color: bpy.props.FloatVectorProperty(
        name = "Text fill color",
        description = "Color and opacity of text object fills (set 0 opacity for no fill)",
        min = 0.0,
        max = 1.0,
        default = [0.0, 0.0, 0.0, 0.0],
        size = 4,
        subtype = "COLOR_GAMMA"
    )

    # Stores the text conversion option
    text_conversion: bpy.props.EnumProperty(
        items = text_options,
        description = "Defines how text objects are exported to SVG",
        default = "text.curve_norot",
        name = "Text conversion"
    )

    # Stores the text font size value
    text_font_size: bpy.props.FloatProperty(
        name = "Text font size",
        description = "Font size of the <text> elements",
        default = 12.0,
        min = 0.0,
        #max = 3.0,
        soft_min = 0.0,
        #soft_max = 3.0
    )

    """ Currently unused
   # Stores the create image file copy option
    copy_image_file: bpy.props.BoolProperty(
        name = "Create image copies",
        description = "If not checked, uses the same ABSOLUTE path for svg <img> as the path specified in Blender for that image."\
            " If checked, creates a file copy of every converted image inside the same directory as the svg output file"\
            " and links the svg <img> elements to those copies using a RELATIVE path",
        default = False
    )"""

    # Stores the viewport camera option
    viewport_camera: bpy.props.EnumProperty(
        items = camera_options,
        description = "Defines which camera views are used for export",
        default = "camera.view",
        name = "Camera source"
    )

    # Stores the camera relative planar light option
    relative_planar_light: bpy.props.BoolProperty(
        name = "Planar light relative to cameras (only works if planar light is selected)",
        description = "If checked, selected planar light direction in MESH Lighting options is relative to each selected camera when using multiple cameras. "\
            "If not checked, selected planar light direction is relative to current 3D Viewport camera. "\
            "For example, if there are two cameras facing opposite to each other and planar light direction is set from left to right, "\
            "both cameras will consider left to right light direction from their point of view if this option is checked "\
            "(meaning their respective light directions will be different, opposite to each other). If this option is not checked, "\
            "both cameras will use the same light direction that will be determined based on the current 3D Viewport camera with which the scene is viewed in Blender "\
            "and the selected planar light direction in the Model Lighting options. Check user guide for example image",
        default = False
    )

    # Stores the selection method option
    selection_method: bpy.props.EnumProperty(
        items = selection_options,
        name = "Object Selection",
        description = "Defines what method will be used for selecting exported objects",
        default = "sel.sel"
    )

    # Stores the modifier option
    apply_modifiers: bpy.props.EnumProperty(
        items = modifiers_options,
        description = "Defines whether objects should be evaluated before conversion (meaning active animation, constraints and modifiers will be taken into account)",
        default = "mod.nomod",
        name = "Evaluation"
    )

    # Stores the selected collection option
    selected_collection: bpy.props.PointerProperty(
        name = "Collection",
        type = bpy.types.Collection,
        description = "All objects/subcollections in this collection will be exported"
    )

    # Stores the global sorting option
    global_sorting_option: bpy.props.EnumProperty(
        items = global_sorting_options,
        description = "Defines what rule is used for depth sorting elements among each other. "\
            "Does not have significant impact unless many objects are clustered closely on top of each other. "\
            "Does not affect how polygons are sorted among each other, check MESH options for that",
        default = "sorting.bbmid",
        name = "Depth sorting"
    )

    # Stores the group by collections option
    group_by_collections: bpy.props.BoolProperty(
        name = "Group by collections",
        description = "If checked, selected objects in the same collection will be converted into the same svg group (<g>)"\
            " (svg file will contain as many groups as there are unique collections with selected objects in the scene)."\
            " If not checked, all selected objects will be converted into a single svg group (file will contain only one group)."\
            " IF AN OBJECT HAS BEEN ASSIGNED TO MULTIPLE COLLECTIONS, ONLY THE FIRST ONE IT WAS ASSIGNED TO IS CONSIDERED" ,
        default = False
    )

    # Stores the sort collections option
    collection_sorting_option: bpy.props.EnumProperty(
        items = collection_sorting_options,
        description = "Defines what rule is used for depth sorting collections among each other",
        default = "coll.hier",
        name = "Collection sorting"
    )

    # Stores the vert precision value
    coord_precision: bpy.props.IntProperty(
        name = "Coordinates precision",
        description = "Number of decimals that the resulting coordinates will be rounded to " + \
            "in the svg file, lesser precision results in a smaller svg file",
        default = 5,
        min = 1,
        max = 15
    )

    # Stores the output filepath
    output_path: bpy.props.StringProperty(
        name = "Output path",
        description = "Defines the path to the outputted file (.svg will be appended if missing)."\
            " If more than one camera is selected, _<CAMERA_NAME> is appended to every generated file",
        default = "C:\\tmp\\output.svg",
        maxlen = 255,
        subtype = "FILE_PATH"
    )

    def get_svg_patterns(self):
        """Gets used patterns from global settings

        :return: Extracted patterns in svg format | empty strings if patterns not used | 
        empty patterns if invalid patterns
        :rtype: str
        """
        polygon_pattern = ""
        curve_pattern = ""
        text_pattern = ""

        if self.polygon_use_pattern:
            pattern_name = "export_svg_global_model_material_pattern"
            pattern = None
            # Finds pattern by looking for the first element with tag ending in "pattern"
            try:
                xml = ET.fromstring(self.polygon_custom_pattern)
                for child in xml.iter():
                    tag = child.tag
                    if len(tag) >= 7 and tag[-7:] == "pattern":
                        pattern = child
                        break
                if pattern is None:
                    raise ValueError("Pattern not found")

                # Sets ID to correspond with class
                pattern.set("id", pattern_name)
                pattern_string = "   " + ET.tostring(pattern, encoding="unicode", method="xml")

                polygon_pattern = pattern_string.replace(">", ">\n   ") + "\n"
            except:
                polygon_pattern = f"   <pattern id=\"{pattern_name}\"></pattern>\n"

        if self.curve_use_pattern:
            pattern_name = "export_svg_global_curve_material_pattern"
            pattern = None
            # Finds pattern by looking for the first element with tag ending in "pattern"
            try:
                xml = ET.fromstring(self.curve_custom_pattern)
                for child in xml.iter():
                    tag = child.tag
                    if len(tag) >= 7 and tag[-7:] == "pattern":
                        pattern = child
                        break
                if pattern is None:
                    raise ValueError("Pattern not found")

                # Sets ID to correspond with class
                pattern.set("id", pattern_name)
                pattern_string = "   " + ET.tostring(pattern, encoding="unicode", method="xml")

                curve_pattern = pattern_string.replace(">", ">\n   ") + "\n"
            except:
                curve_pattern = f"   <pattern id=\"{pattern_name}\"></pattern>\n"

        if self.text_use_pattern:
            pattern_name = "export_svg_global_text_material_pattern"
            pattern = None
            # Finds pattern by looking for the first element with tag ending in "pattern"
            try:
                xml = ET.fromstring(self.text_custom_pattern)
                for child in xml.iter():
                    tag = child.tag
                    if len(tag) >= 7 and tag[-7:] == "pattern":
                        pattern = child
                        break
                if pattern is None:
                    raise ValueError("Pattern not found")

                # Sets ID to correspond with class
                pattern.set("id", pattern_name)
                pattern_string = "   " + ET.tostring(pattern, encoding="unicode", method="xml")

                text_pattern = pattern_string.replace(">", ">\n   ") + "\n"
            except:
                text_pattern = f"   <pattern id=\"{pattern_name}\"></pattern>\n"

        return polygon_pattern + curve_pattern + text_pattern + "\n"

    def polygon_properties_to_svg_style(self, class_name="export_svg_global_model_material"):
        """Converts properties to svg <style> element

        :param class_name: Class name of the style element
        :type class_name: str
        :return: Svg formatted <style> element representing global model settings
        :rtype: str
        """
        style_string = ""

        style_string += f"     .{class_name} {{\n"\
                        f"          stroke-width : {self.polygon_stroke_width};\n"

        # Overrides stroke colors if lighting is disabled or strokes are not set to fills
        if self.polygon_disable_lighting or not self.polygon_stroke_same_as_fill:
            style_string += f"          stroke : rgb({get_rgb_val(self.polygon_stroke_color[0])},"\
                            f"{get_rgb_val(self.polygon_stroke_color[1])},"\
                            f"{get_rgb_val(self.polygon_stroke_color[2])});\n"\
                            f"          stroke-opacity : {self.polygon_stroke_color[3]};\n"

        if self.polygon_dashed_stroke:
            style_string += f"          stroke-dasharray : "
            for x in self.polygon_dash_array:
                if x != 0:
                    style_string += f"{round(x, 2)} "
            style_string += f";\n"
            
        # Overrides fills only if lighting is disabled
        if self.polygon_disable_lighting:
            if self.polygon_use_pattern:
                style_string += f"          fill : url(#{class_name}_pattern);\n"
            else:
                style_string += f"          fill : rgb({get_rgb_val(self.polygon_fill_color[0])},"\
                                f"{get_rgb_val(self.polygon_fill_color[1])},"\
                                f"{get_rgb_val(self.polygon_fill_color[2])});\n"\
                                f"          fill-opacity : {self.polygon_fill_color[3]};\n"
                
        if self.grayscale:
            style_string += f"          filter: saturate(0%);\n"
        
        style_string += f"     }}\n\n"

                        
        return style_string

    def curve_properties_to_svg_style(self, class_name="export_svg_global_curve_material"):
        """Converts properties to svg <style> element

        :param class_name: Class name of the style element
        :type class_name: str
        :return: Svg formatted <style> element representing global curve settings
        :rtype: str
        """
        style_string = ""

        style_string += f"     .{class_name} {{\n"\
                        f"          stroke-width : {self.curve_stroke_width};\n"\
                        f"          stroke : rgb({get_rgb_val(self.curve_stroke_color[0])},"\
                        f"{get_rgb_val(self.curve_stroke_color[1])},"\
                        f"{get_rgb_val(self.curve_stroke_color[2])});\n"\
                        f"          stroke-opacity : {self.curve_stroke_color[3]};\n"

        if self.curve_dashed_stroke:
            style_string += f"          stroke-dasharray : "
            for x in self.curve_dash_array:
                if x != 0:
                    style_string += f"{round(x, 2)} "
            style_string += f";\n"
            
        if self.curve_use_pattern:
            style_string += f"          fill : url(#{class_name}_pattern);\n"
        else:
            style_string += f"          fill : rgb({get_rgb_val(self.curve_fill_color[0])},"\
                            f"{get_rgb_val(self.curve_fill_color[1])},"\
                            f"{get_rgb_val(self.curve_fill_color[2])});\n"\
                            f"          fill-opacity : {self.curve_fill_color[3]};\n"

        if self.grayscale:
            style_string += f"          filter: saturate(0%);\n"

        if self.curve_fill_evenodd:
            style_string += f"          fill-rule : evenodd;\n"
        
        style_string += f"     }}\n\n"
     
        return style_string

    def text_properties_to_svg_style(self, class_name="export_svg_global_text_material"):
        """Converts properties to svg <style> element

        :param class_name: Class name of the style element
        :type class_name: str
        :return: Svg formatted <style> element representing global text settings
        :rtype: str
        """
        style_string = ""

        style_string += f"     .{class_name} {{\n"\
                        f"          stroke-width : {self.text_stroke_width};\n"\
                        f"          stroke : rgb({get_rgb_val(self.text_stroke_color[0])},"\
                        f"{get_rgb_val(self.text_stroke_color[1])},"\
                        f"{get_rgb_val(self.text_stroke_color[2])});\n"\
                        f"          stroke-opacity : {self.text_stroke_color[3]};\n"

        if self.text_dashed_stroke:
            style_string += f"          stroke-dasharray : "
            for x in self.text_dash_array:
                if x != 0:
                    style_string += f"{round(x, 2)} "
            style_string += f";\n"
            
        if self.text_use_pattern:
            style_string += f"          fill : url(#{class_name}_pattern);\n"
        else:
            style_string += f"          fill : rgb({get_rgb_val(self.text_fill_color[0])},"\
                            f"{get_rgb_val(self.text_fill_color[1])},"\
                            f"{get_rgb_val(self.text_fill_color[2])});\n"\
                            f"          fill-opacity : {self.text_fill_color[3]};\n"
        
        if self.grayscale:
            style_string += f"          filter: saturate(0%);\n"

        style_string += f"          font-size : {self.text_font_size}px;\n"\
                        f"     }}\n\n"

        return style_string
    
class ExportSVGMaterialProperties(bpy.types.PropertyGroup):
    """Class storing the material properties of the Export SVG plugin
    """

    # Initializes options for text conversion
    text_options = [
        ("text.raw", "Export As <text>",
         "Converts 3D text into SVG <text> elements with only basic formatting " + \
         "(does not look like the original shape, only raw text is kept)", "", 0),
        ("text.curve_norot", "Export As <path>",
         "Converts the text into curves before exporting to SVG <path> elements. " + \
         "This option will keep the closest resemblance to the original, but the resulting " + \
         "SVG will contain curves instead of text elements", "", 1),
        ("text.curve_rotate", "Face Camera And Export As <path>",
         "Same as Export as <path> but text will be rotated to face the camera", "", 2),
        ("text.mesh_norot", "Export As <polygon>",
         "Converts the text into mesh before exporting to SVG <polygon> elements. " + \
         "Similar to <path> options, but the SVG will contain polygons instead of curves " + \
         "to represent the text. WARNING: This results in many polygons being generated even for a short text", "ERROR", 3),
        ("text.mesh_rotate", "Face Camera And Export As <polygon>",
         "Same as Export as <polygon> but text will be rotated to face the camera. WARNING: This results in many polygons being generated even for a short text", "ERROR", 4) 
    ]

    # Stores the stroke width value
    stroke_width: bpy.props.FloatProperty(
        name = "Stroke width",
        description = "Stroke width",
        default = 1.0,
        min = 0.0,
        #max = 3.0,
        soft_min = 0.0,
        #soft_max = 3.0
    )

    # Stores the stroke color value
    stroke_color: bpy.props.FloatVectorProperty(
        name = "Stroke color and opacity",
        description = "Color and opacity of strokes",
        min = 0.0,
        max = 1.0,
        default = [0.0, 0.0, 0.0, 1.0],
        size = 4,
        subtype = "COLOR_GAMMA"
    )

    # Stores the dashed stroke option
    dashed_stroke: bpy.props.BoolProperty(
        name = "Use dashed stroke",
        description = "Use stroke dash array for the object's stroke",
    )

    # Stores the stroke dash array
    stroke_dash_array: bpy.props.FloatVectorProperty(
        name = "Stroke dash array",
        description = "Array for stroke dash parameters (0 fields are ignored)",
        default = [2, 0, 0, 0],
        min = 0.0,
        max = 100.0,
        size = 4,
        precision = 2,
    )

    def set_use_pattern(self, context):
        if self.use_pattern == True:
            self.ignore_lighting = True

    # Stores the use pattern option
    use_pattern: bpy.props.BoolProperty(
        name = "Use fill pattern",
        description = "Use svg <pattern> to fill object. WARNING: Patterns work when displaying the SVG in web browser "\
                      "but can't be displayed for example in a 2D graphics editor like Inkscape",
        default = False,
        update = set_use_pattern
    )

    # Stores the selected pattern
    custom_pattern: bpy.props.StringProperty(
        name= "Custom pattern",
        description = "Correctly formatted SVG containing <pattern> that will be copied to the output file and assigned to objects. "\
            "Error warning will be displayed if the SVG format is incorrect or <pattern> element is missing",
        default = ""
    )

    # Stores the fill color value
    fill_color: bpy.props.FloatVectorProperty(
        name = "Fill color and opacity",
        description = "Color and opacity of object fill (set 0 opacity for no fill)",
        min = 0.0,
        max = 1.0,
        default = [0.5, 0.5, 0.5, 1.0],
        size = 4,
        subtype = "COLOR_GAMMA"
    )

    # Stores the stroke = fill option
    stroke_equals_fill: bpy.props.BoolProperty(
        name = "Force same color for stroke and fill for MESH/<polygon>",
        description = "If checked, forces the polygon stroke color and style to always be the same as the fill, "\
            "making it appear like there is no visible stroke even when the fill color might change because of lighting. "\
            "If not checked, stroke color is defined by the Stroke Color property.",
        default = False
    )

    # Stores the ignore lighting option
    ignore_lighting: bpy.props.BoolProperty(
        name = "Ignore lighting for polygons",
        description = "If checked, lighting is not taken into account for MESH/polygons, therefore the resulting fill color "\
            "will be the same as the Fill Color property. "\
            "If not checked, Fill Color property defines the base color of the material that will be used as the diffuse color "\
            "and the resulting fill color will be affected by the MESH Lighting options in the main panel",
        default = False
    )

    # Stores the curve merge splines option
    merge_splines: bpy.props.BoolProperty(
        name = "(Type CURVE Only) Merge Splines",
        description = "If checked, all splines of a curve object "\
            "are converted into a single <path> element which results in only the area between them being filled. "\
            "This allows creating empty spaces inside the curve's area, such as the empty space in letter 'A'. "\
            "If not checked, all splines of a curve object are treated as separate curves and each "\
            "spline is converted into its own <path> element ",
        default = False
    )

    # Stores the fill rule evenodd option
    fill_evenodd: bpy.props.BoolProperty(
        name = "(Type CURVE Only) Fill rule evenodd",
        description = "If checked, sets the svg fill-rule attribute to 'evenodd'. "\
            "If not checked, default svg fill-rule is used ('nonzero')",
        default = False
    )

    # Stores the text conversion option
    text_conversion: bpy.props.EnumProperty(
        items = text_options,
        description = "Defines how text objects are exported to SVG",
        default = "text.curve_norot",
        name = "Text conversion"
    )

    # Stores the text font size value
    text_font_size: bpy.props.FloatProperty(
        name = "Text font size",
        description = "Font size of the <text> elements",
        default = 12.0,
        min = 0.0,
        #max = 3.0,
        soft_min = 0.0,
        #soft_max = 3.0
    )

    # Stores the main animation enabling option
    enable_animations: bpy.props.BoolProperty(
        name = "Enable animations",
        description = "Enable CSS animations for this material. Works when the svg is displayed in a web browser",
        default = False
    )

    def get_svg_pattern(self, pattern_name):
        """Gets used pattern from this material (CALL AFTER SETTING CLASS_NAME, WHICH THE ID OF PATTERN IS DERIVED FROM)

        :param class_name: Id name of the style element
        :type class_name: str
        :return: Extracted pattern in svg format | empty pattern if invalid pattern
        :rtype: str
        """
     
        pattern = None
        # Finds pattern by looking for the first element with tag ending in "pattern"
        try:
            xml = ET.fromstring(self.custom_pattern)
            for child in xml.iter():
                tag = child.tag
                if len(tag) >= 7 and tag[-7:] == "pattern":
                    pattern = child
                    break
            if pattern is None:
                raise ValueError("Pattern not found")
        except:
            return f"   <pattern id=\"{pattern_name}\"></pattern>\n"

        # Sets ID to correspond with class
        pattern.set("id", pattern_name)
        pattern_string = "   " + ET.tostring(pattern, encoding="unicode", method="xml")

        return pattern_string.replace(">", ">\n   ") + "\n"

    def to_svg_style(self, class_name, material, grayscale = False):
        """Converts properties to two svg <style> elements, one general and one for polygons

        :param class_name: Class name of the style element
        :type class_name: str
        :param material: Original (parent) material that these properties belong to
        :type material: bpy.types.Material
        :param grayscale: If true, adds grayscale filter to the class definition
        :type grayscale: bool
        :return: Svg formatted <style> element
        :rtype: str
        """
        style_string = ""

        style_string += f"     .{class_name} {{\n"\
                        f"          stroke-width : {self.stroke_width};\n"\
                        f"          stroke : rgb({get_rgb_val(self.stroke_color[0])},"\
                        f"{get_rgb_val(self.stroke_color[1])},"\
                        f"{get_rgb_val(self.stroke_color[2])});\n"\
                        f"          stroke-opacity : {self.stroke_color[3]};\n"

        if self.dashed_stroke:
            style_string += f"          stroke-dasharray : "
            for x in self.stroke_dash_array:
                if x != 0:
                    style_string += f"{round(x, 2)} "
            style_string += f";\n"
            
        if self.use_pattern:
            style_string += f"          fill : url(#{class_name}_pattern);\n"
        else:
            style_string += f"          fill : rgb({get_rgb_val(self.fill_color[0])},"\
                            f"{get_rgb_val(self.fill_color[1])},"\
                            f"{get_rgb_val(self.fill_color[2])});\n"\
                            f"          fill-opacity : {self.fill_color[3]};\n"
        
        if self.fill_evenodd:
            style_string += f"          fill-rule : evenodd;\n"

        if self.enable_animations:
            style_string += f"          {material.export_svg_animation_properties.to_css_attribute(ANIMATION_PREFIX + class_name)}\n"
            
        if grayscale:
            style_string += f"          filter: saturate(0%);\n"

        style_string += f"          font-size : {self.text_font_size}px;\n"\
                        f"     }}\n\n"


        polygon_style_string = ""

        polygon_style_string += f"     .polygon_{class_name} {{\n"\
                        f"          stroke-width : {self.stroke_width};\n"
        
        # Overrides stroke colors if lighting is disabled or strokes are not set to fills
        if self.ignore_lighting or not self.stroke_equals_fill:
            polygon_style_string += f"          stroke : rgb({get_rgb_val(self.stroke_color[0])},"\
                                    f"{get_rgb_val(self.stroke_color[1])},"\
                                    f"{get_rgb_val(self.stroke_color[2])});\n"\
                                    f"          stroke-opacity : {self.stroke_color[3]};\n"

        if self.dashed_stroke:
            polygon_style_string += f"          stroke-dasharray : "
            for x in self.stroke_dash_array:
                if x != 0:
                    polygon_style_string += f"{round(x, 2)} "
            polygon_style_string += f";\n"
        
        # Overrides fills only if lighting is disabled
        if self.ignore_lighting:
            if self.use_pattern:
                polygon_style_string += f"          fill : url(#{class_name}_pattern);\n"
            else:
                polygon_style_string += f"          fill : rgb({get_rgb_val(self.fill_color[0])},"\
                                        f"{get_rgb_val(self.fill_color[1])},"\
                                        f"{get_rgb_val(self.fill_color[2])});\n"\
                                        f"          fill-opacity : {self.fill_color[3]};\n"
        
        if self.enable_animations:
            polygon_style_string += f"          {material.export_svg_animation_properties.to_css_attribute(ANIMATION_PREFIX + class_name)}\n"

        if grayscale:
            polygon_style_string += f"          filter: saturate(0%);\n"

        polygon_style_string += f"          font-size : {self.text_font_size}px;\n"\
                                f"     }}\n\n"

        return style_string + polygon_style_string

class ExportSVGKeyframeProperties(bpy.types.PropertyGroup):
    """Class storing the properties of individual keyframes of animation
    """

    # Initializes options for text conversion
    translation_units_options = [
        ("px", "px",
         "Use pixels as units for translation", "", 0),
        ("em", "em",
         "Use em as units for translation", "", 1),
        ("rem", "rem",
         "Use rem as units for translation", "", 2),
        ("in", "in",
         "Use inches as units for translation", "", 3),
    ]

    # Stores the name of this keyframe displayed in the keyframe list
    name: bpy.props.StringProperty(
        name = "Name",
        description = "A name for this keyframe",
        default = "Untitled Keyframe"
    )

    # Stores the percentage display value of this keyframe
    percentage: bpy.props.IntProperty(
        name = "Percentage",
        description = "A percentage of the time through the animation sequence at which the specified keyframe should occur",
        default = 50,
        min = 0,
        max = 100,
        soft_min = 0,
        soft_max = 100,
        subtype = "PERCENTAGE"
    )

    # Stores transformation application option
    transform: bpy.props.BoolProperty(
        name = "Apply transformations",
        description = "If checked, applies the specified translation, scaling, rotation and skew to this keyframe "\
                      "WARNING: Only an experimental feature, has bad performance when used in a scene with many polygons",
    )

    # Stores the selected transform origin
    transform_origin: bpy.props.PointerProperty(
        name = "Transform origin",
        type = bpy.types.Object,
        description = "Position of this object will be used as the transform origin attribute (if none is selected, origin is defaulted to top left corner). " \
            "This property affects certain transformations like rotation, where for example it defines point around which to rotate. "\
            "WARNING: Due to certain limitations, this object must NOT be behind the camera, otherwise it will be ignored"
    )

    # Stores the translation units option
    translate_units: bpy.props.EnumProperty(
        items = translation_units_options,
        description = "Defines which units to use when specifying translation",
        default = "px",
        name = "Translation units"
    )

    # Stores the translation values
    translate: bpy.props.FloatVectorProperty(
        name = "Translate",
        description = "Array for XYZ translation parameters",
        default = [0, 0, 0],
        size = 3,
        precision = 2,
        subtype = "XYZ"
    )

    # Stores the scale values
    scale: bpy.props.FloatVectorProperty(
        name = "Scale",
        description = "Array for XYZ scale parameters",
        default = [1, 1, 1],
        size = 3,
        precision = 2,
        subtype = "XYZ"
    )

    # Stores the 3D rotate values
    rotate3d: bpy.props.FloatVectorProperty(
        name = "Rotate",
        description = "Array for XYZ rotate parameters (You can use (1, 0, 0) for rotation along X-axis; (0, 1, 0) for Y-axis or (0, 0, 1) for Z-axis (which is the same as a 2D rotation))",
        default = [0, 0, 1],
        size = 3,
        precision = 2,
        subtype = "XYZ"
    )

    # Stores the rotation angle value
    rotate_angle: bpy.props.FloatProperty(
        name = "Rotate angle",
        description = "Angle in degrees by which to rotate",
        default = 0,
        precision = 2,
        subtype = "ANGLE"
    )

    # Stores the skew values
    skew: bpy.props.FloatVectorProperty(
        name = "Skew",
        description = "Array for XY skew parameters",
        default = [0, 0],
        size = 2,
        precision = 2,
        subtype = "XYZ"
    )

    # Stores the stroke width animation option
    a_stroke_width: bpy.props.BoolProperty(
        name = "Animate stroke width",
        description = "If checked, animates stroke width attribute for this keyframe, otherwise ignores it",
    )

    # Stores the stroke color animation option
    a_stroke_color: bpy.props.BoolProperty(
        name = "Animate stroke color and opacity",
        description = "If checked, animates stroke color and opacity attribute for this keyframe, otherwise ignores it",
    )

    # Stores the dashed stroke animation option
    a_dashed_stroke: bpy.props.BoolProperty(
        name = "Animate dashed stroke",
        description = "If checked, animates dashed stroke attribute for this keyframe, otherwise ignores it",
    )

    # Stores the fill color animation option
    a_fill_color: bpy.props.BoolProperty(
        name = "Animate fill color and opacity",
        description = "If checked, animates fill color and opacity attribute for this keyframe, otherwise ignores it",
    )

    # Stores the stroke width value
    stroke_width: bpy.props.FloatProperty(
        name = "Stroke width",
        description = "Stroke width",
        default = 1.0,
        min = 0.0,
        #max = 3.0,
        soft_min = 0.0,
        #soft_max = 3.0
    )

    # Stores the stroke color value
    stroke_color: bpy.props.FloatVectorProperty(
        name = "Stroke color",
        description = "Custom color of strokes",
        min = 0.0,
        max = 1.0,
        default = [0.0, 0.0, 0.0, 1.0],
        size = 4,
        subtype = "COLOR_GAMMA"
    )

    # Stores the stroke dash array
    stroke_dash_array: bpy.props.FloatVectorProperty(
        name = "Stroke dash array",
        description = "Array for stroke dash parameters (0 fields are ignored)",
        default = [2, 0, 0, 0],
        min = 0.0,
        max = 100.0,
        size = 4,
        precision = 2,
    )

    # Stores the fill color value
    fill_color: bpy.props.FloatVectorProperty(
        name = "Fill color",
        description = "Color and opacity of object fill (set 0 opacity for no fill)",
        min = 0.0,
        max = 1.0,
        default = [0.5, 0.5, 0.5, 1.0],
        size = 4,
        subtype = "COLOR_GAMMA"
    )

    """
    def set_use_pattern(self, context):
        if self.use_pattern == True:
            self.ignore_lighting = True

    # Stores the use pattern option
    use_pattern: bpy.props.BoolProperty(
        name = "Use fill pattern",
        description = "Use svg <pattern> to fill object",
        default = False,
        update = set_use_pattern
    )

    # Stores the selected pattern
    custom_pattern: bpy.props.StringProperty(
        name= "Custom pattern",
        description = "Correctly formatted SVG containing <pattern> that will be copied to the output file and assigned to objects. "\
            "Error warning will be displayed if the SVG format is incorrect or <pattern> element is missing",
        default = ""
    )"""

    def to_css_keyframe(self, camera_info):
        """Converts this property object into a CSS animation keyframe

        :param camera_info: Information about the camera used to generate this file (required for transform origin calculation)
        :type camera_info: CameraInfo
        :return: Keyframe definition in CSS format describing all properties of the keyframe
        :rtype: str
        """
        keyframe_string = f"       {self.percentage}% {{\n"

        if self.a_stroke_width:
            keyframe_string += f"          stroke-width : {self.stroke_width};\n"

        if self.a_stroke_color:
            keyframe_string += f"          stroke : rgb({get_rgb_val(self.stroke_color[0])},"\
                               f"{get_rgb_val(self.stroke_color[1])},"\
                               f"{get_rgb_val(self.stroke_color[2])});\n"\
                               f"          stroke-opacity : {self.stroke_color[3]};\n"

        if self.a_dashed_stroke:
            keyframe_string += f"          stroke-dasharray : "
            for x in self.stroke_dash_array:
                if x != 0:
                    keyframe_string += f"{round(x, 2)} "
            keyframe_string += f";\n"

        if self.a_fill_color:
            keyframe_string += f"          fill : rgb({get_rgb_val(self.fill_color[0])},"\
                               f"{get_rgb_val(self.fill_color[1])},"\
                               f"{get_rgb_val(self.fill_color[2])});\n"\
                               f"          fill-opacity : {self.fill_color[3]};\n"

        t_units = self.translate_units
        r_units = "rad"
        s_units = "deg"

        if self.transform:
            keyframe_string += f"          transform: "\
                               f"translate3d({self.translate[0]}{t_units},{self.translate[1]}{t_units},{self.translate[2]}{t_units}) "\
                               f"scale3d({self.scale[0]},{self.scale[1]},{self.scale[2]}) "\
                               f"rotate3d({self.rotate3d[0]},{self.rotate3d[1]},{self.rotate3d[2]},{self.rotate_angle}{r_units}) "\
                               f"skew({self.skew[0]}{s_units},{self.skew[1]}{s_units});\n"

            if self.transform_origin is not None:
                origin_location = camera_info.world_to_viewport(self.transform_origin.location)
                if origin_location is not None:
                    keyframe_string += f"          transform-origin: {origin_location[0]}px {origin_location[1]}px;\n"\

        keyframe_string += "       }\n\n"

        return keyframe_string

class ExportSVGAnimationProperties(bpy.types.PropertyGroup):
    """Class storing the animation properties of a material of the Export SVG plugin
    """

    # Initializes options for text conversion
    timing_function_options = [
        ("ease", "Ease",
         "Faster in middle, slows down at the end", "", 0),
        ("linear", "Linear",
         "Linear speed", "", 1),
        ("ease-in", "Ease In",
         "Starts slow and speeds up", "", 2),
        ("ease-out", "Ease Out",
         "Starts fast and slows down", "", 3),
        ("ease-in-out", "Ease In Out",
         "Starts slow, speeds up and slows down again", "", 4) 
    ]

    # Initializes options for direction
    direction_options = [
        ("normal", "Normal",
         "Animation plays forwards each cycle", "", 0),
        ("reverse", "Reverse",
        "Animation plays backwards each cycle", "", 1),
        ("alternate", "Alternate",
        "Animation reverses direction each cycle, first iteration is forwards", "", 2),
        ("alternate-reverse", "Alternate Reverse",
        "Animation reverses direction each cycle, first iteration is backwards", "", 3),
    ]

    # Initializes options for fill-mode
    fill_mode_options = [
        ("none", "None",
        "Animation will not apply any style while it's not executing", "", 0),
        ("forwards", "Forwards",
        "Object will retain styles set by the last keyframe after the animation ends", "", 1),
        ("backwards", "Backwards",
        "Object will start with a style set by the first keyframe before the animation begins", "", 2),
        ("both", "Both",
        "Combines options Forwards and Backwards", "", 3),
    ]

    def set_linked_material(self, context):
        # Checks for loops in linked materials and unsets if needed
        if self.linked_material is not None:
            i = 0
            new_name = self.linked_material.name
            next = self.linked_material
            while next.export_svg_animation_properties.linked_material is not None:
                next = next.export_svg_animation_properties.linked_material
                i += 1
                if i >= 10:
                    self.linked_material = None
                    display_message([f"Unable to link to {new_name} because an endless loop or a chain longer than 10 materials would be created"], "Error", "ERROR")
                    return

    # Stores the material animation linking option
    linked_material: bpy.props.PointerProperty(
        name = "Linked material",
        type = bpy.types.Material,
        description = "Animation properties/keframes will be copied from the selected material instead of setting them individually. "\
            "It is possible to chain these links (by linking a material to another material that is also linked), but if you try to set link to a material that would create "\
            "a chain longer than 10 materials or a cycled chain, this property will be reset automatically",
        update = set_linked_material
    )

    # Stores the animation duration value in seconds
    duration: bpy.props.FloatProperty(
        name = "Duration",
        description = "Duration of one animation cycle in seconds",
        default = 2.0,
        min = 0.0,
        soft_min = 0.0,
    )

    # Stores the animation delay value in seconds
    delay: bpy.props.FloatProperty(
        name = "Delay",
        description = "Delay of the start of the animation in seconds (can be negative value)",
        default = 0.0,
    )

    # Stores the infinite iteration option
    infinite: bpy.props.BoolProperty(
        name = "Infinite",
        description = "If checked, the animation will repeat infinitely",
        default = True
    )

    # Stores the iteration count
    iteration_count: bpy.props.FloatProperty(
        name = "Iteration count",
        description = "Number of iterations to be played, can be decimal (for example value 0.5 means only half of the cycle will play)",
        default = 1.0,
        min = 0.0,
        soft_min = 0.0,
    )

    # Stores the direction option
    direction: bpy.props.EnumProperty(
        items = direction_options,
        description = "Defines direction in which the animation should be played",
        default = "normal",
        name = "Direction"
    )

    # Stores the fillmode option
    fill_mode: bpy.props.EnumProperty(
        items = fill_mode_options,
        description = "Defines how CSS animation styles are applied before and after the animation",
        default = "none",
        name = "Fill Mode"
    )

    # Stores the timing function option
    timing_function: bpy.props.EnumProperty(
        items = timing_function_options,
        description = "Defines how an animation progresses through each cycle",
        default = "ease",
        name = "Timing function"
    )

    # Stores index of currently selected keyframe (internal, not diplayed to user)
    keyframe_index: bpy.props.IntProperty(
        name = "Keframe index",
        default = 0
    )

    # Stores individual keyframes in a collection (internal, not diplayed to user)
    keyframes: bpy.props.CollectionProperty(
        type = ExportSVGKeyframeProperties,
    )

    def to_css_attribute(self, keyframes_name, recursive = True):
        """Converts this property object into a CSS animation attribute

        :param keyframes_name: Name of the keyframes associated with this animation
        :type keyframes_name: str
        :param recursive: If True, delegates the call to a linked material if there is one, 
        if False, converts its own properties
        :type recursive: bool
        :return: Animation attribute in CSS format describing all properties of the animation
        :rtype: str
        """

        # If linked to other material, delegates the call up to 10 links forward 
        # (stops after 10 to prevent any endless loops that might occur for some reason)
        if recursive and self.linked_material is not None:
            i = 0
            next = self.linked_material
            while next.export_svg_animation_properties.linked_material is not None and i < 10:
                next = next.export_svg_animation_properties.linked_material
                i += 1
            return next.export_svg_animation_properties \
                .to_css_attribute(keyframes_name, recursive = False)

        animation_string = f"animation: {self.duration}s {self.timing_function} {self.delay}s "

        if self.infinite:
            animation_string += "infinite "
        else:
            animation_string += f"{self.iteration_count} "
        
        animation_string += f"{self.direction} {self.fill_mode} running {keyframes_name};"

        return animation_string

    def to_css_keyframes(self, keyframes_name, camera_info, recursive = True):
        """Converts the keyframes collection of this property object into a 
        CSS keyframes definition

        :param keyframes_name: Name of the keyframes associated with this animation
        :type keyframes_name: str
        :param camera_info: Information about the camera used to generate this file 
        (required for transform origin calculation)
        :type camera_info: CameraInfo
        :param recursive: If True, delegates the call to a linked material if there is one, 
        if False, converts its own keyframes
        :type recursive: bool
        :return: Keyframes definition in CSS format containing all defined keyframes
        :rtype: str
        """

        # If linked to other material, delegates the call up to 10 links forward 
        # (stops after 10 to prevent any endless loops that might occur for some reason)
        if recursive and self.linked_material is not None:
            i = 0
            next = self.linked_material
            while next.export_svg_animation_properties.linked_material is not None and i < 10:
                next = next.export_svg_animation_properties.linked_material
                i += 1
            return next.export_svg_animation_properties \
                .to_css_keyframes(keyframes_name, camera_info, recursive = False)

        keyframes_string = f"     @keyframes {keyframes_name} {{\n"

        keyframe_list = []
        for keyframe in self.keyframes.values():
            keyframe_list.append(keyframe)
        keyframe_list.sort(key = lambda x: x.percentage)

        for keyframe in keyframe_list:
            keyframes_string += keyframe.to_css_keyframe(camera_info)

        keyframes_string += "     }\n"

        return keyframes_string

#
# BSP NODE TYPE
#

class BSPNode:
    """Class representing a BSP Node
    """

    def __init__(self):
        """Constructor method
        """
        self.front_node = None
        self.back_node = None
        self.is_leaf = True
        self.polygon_list = list()

#
# VIEW TYPES
#

class ViewType(ABC):

    @abstractmethod
    def to_svg(self, precision):
        pass

    @abstractmethod
    def get_depth(self, option):
        pass

class ViewPolygon(ViewType):
    """Class representing a polygon in viewport
    """

    def __init__(self, verts, depth, rgb_color, opacity, 
                 set_bounds=False, material_name="", 
                 ignored_lighting=False, stroke_equals_fill=False):
        """Constructor method of ViewPolygon type

        :param verts: Vertices of the polygon
        :type verts: List of float[3]
        :param depth: Depth of the polygon
        :type depth: float
        :param rgb_color: Color of the polygon
        :type rgb_color: float[3]
        :param opacity: Opacity of the polygon
        :type opacity: float
        :param set_bounds: Calculates bounds of the polygon if True, defaults to False
        :type set_bounds: bool, optional
        :param material_name: name of the material that is set to this polygon, defaults to ""
        :type material_name: str, optional
        :param ignored_lighting: True if material of this polygon ignores lighting, 
        defaults to False
        :type ignored_lighting: bool, optional
        :param stroke_equals_fill: True if the stroke of this polygon is 
        supposed to be the same as the fill, defaults to False
        :type stroke_equals_fill: bool, optional
        """
        # vert = (x, y, z)
        self.verts = verts
        self.depth = depth
        # rgb = (r, g, b)
        self.rgb_color = rgb_color
        self.opacity = opacity
        self.material_name = material_name
        self.ignored_lighting = ignored_lighting
        self.stroke_equals_fill = stroke_equals_fill
        self.normal = get_normal(verts)
        # Newell marked
        self.marked = False
        # Bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        self.bounds = [0, 0, 0, 0, 0, 0]
        if set_bounds:
            self.bounds = [verts[0][0], verts[0][0],
                           verts[0][1], verts[0][1],
                           verts[0][2], verts[0][2]]
            for vert in self.verts:
                self.bounds[0] = min(vert[0], self.bounds[0])
                self.bounds[1] = max(vert[0], self.bounds[1])
                self.bounds[2] = min(vert[1], self.bounds[2])
                self.bounds[3] = max(vert[1], self.bounds[3])
                self.bounds[4] = min(vert[2], self.bounds[4])
                self.bounds[5] = max(vert[2], self.bounds[5])

    def to_svg_shape_only(self, precision):
        """Converts this viewport object to svg formatted string without attributes (like color)

        :param precision: Number of decimal places for coordinates (1-15)
        :type precision: int
        :return: String in svg format defining the ViewPolygon
        :rtype: str
        """
        polygon_string = "   <polygon points=\""

        # Prints 2D vertices in a sequence as a polygon
        for vert in self.verts:
            polygon_string += f"{round(vert[0], precision)},{round(vert[1], precision)} "

        polygon_string += f"\" />\n"

        return polygon_string

    def to_svg(self, precision):
        """Converts this viewport object to svg formatted string

        :param precision: Number of decimal places for coordinates (1-15)
        :type precision: int
        :return: String in svg format defining the ViewPolygon
        :rtype: str
        """
        polygon_string = "   <polygon points=\""

        # Prints 2D vertices in a sequence as a polygon
        for vert in self.verts:
            polygon_string += f"{round(vert[0], precision)},{round(vert[1], precision)} "

        # Sets custom colour and opacity of the polygons only if lighting is active, 
        # otherwise uses material
        if not self.ignored_lighting:
            polygon_string += f"\" fill=\"rgb({get_rgb_val(self.rgb_color[0])},"\
                f"{get_rgb_val(self.rgb_color[1])},"\
                f"{get_rgb_val(self.rgb_color[2])})\""
            if self.opacity != 1.0:
                polygon_string += f" fill-opacity=\"{round(self.opacity, 4)}\" "\
            
            # Sets custom colour and opacity of strokes only if lighting is active and 
            # strokes are same as fills, otherwise uses material
            if self.stroke_equals_fill:
                polygon_string += f" stroke="\
                    f"\"rgb({get_rgb_val(self.rgb_color[0])},"\
                    f"{get_rgb_val(self.rgb_color[1])},"\
                    f"{get_rgb_val(self.rgb_color[2])})\""

                if self.opacity != 1.0:
                    polygon_string += f" stroke-opacity=\"{round(self.opacity, 4)}\" "
        else:
            polygon_string += f"\" "
        
        polygon_string += f" class=\"{self.material_name}\" />\n"
            
        return polygon_string

    def get_depth(self, option):
        """Gets depth of this element based on its bounding box

        :param option: 1 for zMin, 2 for zMax, 3 for zMiddle
        :type option: int
        """
        if option == 1:
            return self.bounds[4]
        elif option == 2:
            return self.bounds[5]
        elif option == 3:
            return (self.bounds[4] + self.bounds[5]) / 2.0
        else:
            raise TypeError("Invalid sorting option")

    @staticmethod
    def recalculate_bounds(view_polygon):
        """Recalculates the bounds of the polygon

        :param view_polygon: Polygon to recalculate
        :type view_polygon: ViewPolygon
        """
        verts = view_polygon.verts
        view_polygon.bounds = [verts[0][0], verts[0][0],
                  verts[0][1], verts[0][1],
                  verts[0][2], verts[0][2]]
        for vert in verts:
            view_polygon.bounds[0] = min(vert[0], view_polygon.bounds[0])
            view_polygon.bounds[1] = max(vert[0], view_polygon.bounds[1])
            view_polygon.bounds[2] = min(vert[1], view_polygon.bounds[2])
            view_polygon.bounds[3] = max(vert[1], view_polygon.bounds[3])
            view_polygon.bounds[4] = min(vert[2], view_polygon.bounds[4])
            view_polygon.bounds[5] = max(vert[2], view_polygon.bounds[5])

class ViewCurve(ViewType):
    """Class representing a curve in viewport
    """

    def __init__(self, bezier_points, cyclic, material_name, bounds, curved=True):
        """Constructor of the ViewCurve type

        :param bezier_points: Bezier points of the curve
        :type bezier_points: List of (float[3], float[3], float[3])
        :param cyclic: If True, connects last point with the first one
        :type cyclic: bool
        :param material_name: name of the material that is set to this curve
        :type material_name: str
        :param bounds: Bounding box of the curve [xMin, xMax, yMin, yMax, zMin, zMax]
        :type bounds: float[6]
        :param curved: If True, prints curveto commands along with control points 
        to create a curved path, 
        if False, creates a straight path connecting individual main points with a line, 
        defaults to True
        :type curved: bool, optional
        """
        # Bezier_point == (handle_left_pos, handle_right_pos, coord_pos)
        self.bezier_points = bezier_points
        self.cyclic = cyclic
        self.material_name = material_name
        self.curved = curved
        # Bounding box [0, 0, 0, 0, zMin, zMax] - first 4 currently unused and not calculated
        self.bounds = bounds

    def to_svg_coords_only(self, precision):
        """Converts this viewport object to svg formatted string with only path commands

        :param precision: Number of decimal places for coordinates (1-15)
        :type precision: int
        :return: String in svg format defining the d attribute of the path element
        :rtype: str
        """
        curve_string = ""
        points = self.bezier_points

        # First point moveto command (points[point_index] [lhandle/rhandle/coord] [x/y/z])
        curve_string += f"M {round(points[0][2][0], precision)},"\
                        f"{round(points[0][2][1], precision)} "

        # Curveto command for every point other than the first and last
        for i in range(1, len(points)):
            # Uses (right handle of previous point, 
            # left handle of current point, 
            # coord of current point)
            curve_string += f"C {round(points[i-1][1][0], precision)},{round(points[i-1][1][1], precision)} "\
                            f"{round(points[i][0][0], precision)},{round(points[i][0][1], precision)} "\
                            f"{round(points[i][2][0], precision)},{round(points[i][2][1], precision)} "

        # If cyclic, connects the last and first points
        if self.cyclic:
            curve_string += f"C {round(points[-1][1][0], precision)},{round(points[-1][1][1], precision)} "\
                            f"{round(points[0][0][0], precision)},{round(points[0][0][1], precision)} "\
                            f"{round(points[0][2][0], precision)},{round(points[0][2][1], precision)} "

        return curve_string

    def to_svg_shape_only(self, precision):
        """Converts this viewport object to svg formatted string without any other attributes 
        (like color)

        :param precision: Number of decimal places for coordinates (1-15)
        :type precision: int
        :return: String in svg format defining the ViewCurve
        :rtype: str
        """
        curve_string = "   <path d=\""
        points = self.bezier_points

        # First point moveto command (points[point_index] [lhandle/rhandle/coord] [x/y/z])
        curve_string += f"M {round(points[0][2][0], precision)},"\
                        f"{round(points[0][2][1], precision)} "

        # Curveto command for every point other than the first and last
        for i in range(1, len(points)):
            # Uses (right handle of previous point, 
            # left handle of current point, 
            # coord of current point)
            curve_string += f"C {round(points[i-1][1][0], precision)},{round(points[i-1][1][1], precision)} "\
                            f"{round(points[i][0][0], precision)},{round(points[i][0][1], precision)} "\
                            f"{round(points[i][2][0], precision)},{round(points[i][2][1], precision)} "

        # If cyclic, connects the last and first points
        if self.cyclic:
            curve_string += f"C {round(points[-1][1][0], precision)},{round(points[-1][1][1], precision)} "\
                            f"{round(points[0][0][0], precision)},{round(points[0][0][1], precision)} "\
                            f"{round(points[0][2][0], precision)},{round(points[0][2][1], precision)} "

        curve_string += "\" />\n"

        return curve_string

    def to_svg(self, precision):
        """Converts this viewport object to svg formatted string

        :param precision: Number of decimal places for coordinates (1-15)
        :type precision: int
        :param curved: If True, prints curveto commands along with control points to create a curved path, 
        if False, creates a straight path connecting individual main points with a line
        :type curved: bool
        :return: String in svg format defining the ViewCurve
        :rtype: str
        """
        curve_string = "   <path d=\""
        points = self.bezier_points

        if self.curved:
            # First point moveto command (points[point_index] [lhandle/rhandle/coord] [x/y/z])
            curve_string += f"M {round(points[0][2][0], precision)},"\
                            f"{round(points[0][2][1], precision)} "

            # Curveto command for every point other than the first and last
            for i in range(1, len(points)):
                # Uses (right handle of previous point, 
                # left handle of current point, 
                # coord of current point)
                curve_string += f"C {round(points[i-1][1][0], precision)},{round(points[i-1][1][1], precision)} "\
                                f"{round(points[i][0][0], precision)},{round(points[i][0][1], precision)} "\
                                f"{round(points[i][2][0], precision)},{round(points[i][2][1], precision)} "
        else:
            # First point moveto command (points[point_index] [lhandle/rhandle/coord] [x/y/z])
            curve_string += f"M {round(points[0][2][0], precision)},"\
                            f"{round(points[0][2][1], precision)} "

            # Moveto command for every point other than the first and last
            for i in range(1, len(points)):
                curve_string += f"{round(points[i][2][0], precision)},{round(points[i][2][1], precision)} "

        # If cyclic, connects the last and first points
        if self.cyclic:
            if self.curved:
                curve_string += f"C {round(points[-1][1][0], precision)},{round(points[-1][1][1], precision)} "\
                                f"{round(points[0][0][0], precision)},{round(points[0][0][1], precision)} "\
                                f"{round(points[0][2][0], precision)},{round(points[0][2][1], precision)} "
            else:
                curve_string += f"M {round(points[0][2][0], precision)},"\
                                f"{round(points[0][2][1], precision)} "

        curve_string += f"\" class=\"{self.material_name}\" "

        curve_string += " />\n"

        return curve_string

    def get_depth(self, option):
        """Gets depth of this element based on its bounding box

        :param option: 1 for zMin, 2 for zMax, 3 for zMiddle
        :type option: int
        """
        if option == 1:
            return self.bounds[4]
        elif option == 2:
            return self.bounds[5]
        elif option == 3:
            return (self.bounds[4] + self.bounds[5]) / 2.0
        else:
            raise TypeError("Invalid sorting option")

class ViewText(ViewType):
    """Class representing a text in viewport
    """

    def __init__(self, content, bounds, material_name):
        """Constructor of the ViewText type

        :param content: Text content
        :type content: str
        :param bounds: Bounding box of the text [xMin, xMax, yMin, yMax, zMin, zMax]
        :type bounds: float[6]
        :param material_name: name of the material that is set to this text
        :type material_name: str
        """
        self.content = content
        self.material_name = material_name
        # Bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        self.bounds = bounds

    def to_svg(self, precision):
        """Converts this viewport object to svg formatted string

        :param precision: Number of decimal places for coordinates (1-15)
        :type precision: int
        :return: String in svg format defining the ViewText
        :rtype: str
        """
        
        lines = self.content.split("\n")

        text_string = f"   <text x=\"{round(self.bounds[0], precision)}\""\
                      f" y=\"{round(self.bounds[2], precision)}\""\
                      f" class=\"{self.material_name}\" >\n"
                      #f" fill="\
                      #f"\"rgb({int(self.fill_color[0])},"\
                      #f"{int(self.fill_color[1])},"\
                      #f"{int(self.fill_color[2])})\""\
                      #f" opacity=\"{round(self.opacity, 4)}\""\
                      #f" font-size=\"{self.fontsize}\"\
                      #f" font-family=\"Arial, Helvetica, sans-serif\">\n"
                      
        # Creates <tspan> for every line of text
        for line in lines:
            text_string += f"    <tspan x=\"{self.bounds[0]}\" dy=\"1.0em\">{line}</tspan>\n"
    
        text_string += f"   </text>\n"

        return text_string

    def get_depth(self, option):
        """Gets depth of this element based on its bounding box

        :param option: 1 for zMin, 2 for zMax, 3 for zMiddle
        :type option: int
        """
        if option == 1:
            return self.bounds[4]
        elif option == 2:
            return self.bounds[5]
        elif option == 3:
            return (self.bounds[4] + self.bounds[5]) / 2.0
        else:
            raise TypeError("Invalid sorting option")

class ViewCurveGroup(ViewType):
    """Class representing a group of curves in viewport 
    (unlike ViewTextCurve, curves are not merged and each curve can have a different material)
    """

    def __init__(self, curves):
        """Constructor of the ViewCurveGroup type

        :param curves: Curves that are part of this group
        :type curves: List of ViewCurve
        """
        self.curves = curves
        # Bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        # Gets viewport bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        bounds = [inf, -inf, inf, -inf, inf, -inf]
        for curve in curves:
            bounds[0] = min(bounds[0], curve.bounds[0])
            bounds[1] = max(bounds[1], curve.bounds[1])
            bounds[2] = min(bounds[2], curve.bounds[2])
            bounds[3] = max(bounds[3], curve.bounds[3])
            bounds[4] = min(bounds[4], curve.bounds[4])
            bounds[5] = max(bounds[5], curve.bounds[5])
        self.bounds = bounds

    def to_svg(self, precision):
        """Converts this viewport object to svg formatted string

        :param precision: Number of decimal places for coordinates (1-15)
        :type precision: int
        :return: String in svg format defining the ViewCurveGroup
        :rtype: str
        """

        text_string = f"  <g>\n"

        # Converts every individual curve
        for curve in self.curves:
            text_string += curve.to_svg(precision)

        text_string += f"  </g>\n"

        return text_string

    def get_depth(self, option):
        """Gets depth of this element based on its bounding box

        :param option: 1 for zMin, 2 for zMax, 3 for zMiddle
        :type option: int
        """
        if option == 1:
            return self.bounds[4]
        elif option == 2:
            return self.bounds[5]
        elif option == 3:
            return (self.bounds[4] + self.bounds[5]) / 2.0
        else:
            raise TypeError("Invalid sorting option")

class ViewTextCurve(ViewType):
    """Class representing a text in viewport converted to curves 
    (also used to represent a group of curves)
    """

    def __init__(self, curves, bounds, material_name):
        """Constructor of the ViewTextCurve type

        :param curves: Curves that are part of this group
        :type curves: List of ViewCurve
        :param bounds: Bounding box of the text [xMin, xMax, yMin, yMax, zMin, zMax]
        :type bounds: float[6]
        :param material_name: name of the material that is set to this text
        :type material_name: str
        """
        self.curves = curves
        self.material_name = material_name
        # Bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        self.bounds = bounds

    def to_svg(self, precision):
        """Converts this viewport object to svg formatted string

        :param precision: Number of decimal places for coordinates (1-15)
        :type precision: int
        :return: String in svg format defining the ViewTextCurve
        :rtype: str
        """

        text_string = f"  <g"

        text_string += f" class=\"{self.material_name}\" >\n"
        text_string += "   <path d=\""

        # Converts every individual curve
        for curve in self.curves:
            text_string += curve.to_svg_coords_only(precision) + " "

        text_string += "\" />\n"
        text_string += f"  </g>\n"

        return text_string

    def get_depth(self, option):
        """Gets depth of this element based on its bounding box

        :param option: 1 for zMin, 2 for zMax, 3 for zMiddle
        :type option: int
        """
        if option == 1:
            return self.bounds[4]
        elif option == 2:
            return self.bounds[5]
        elif option == 3:
            return (self.bounds[4] + self.bounds[5]) / 2.0
        else:
            raise TypeError("Invalid sorting option")

class ViewTextMesh(ViewType):
    """Class representing a text in viewport converted to polygons
    """

    def __init__(self, polygons, bounds, material_name):
        """Constructor of the ViewTextMesh type

        :param polygons: Polygons that are part of this group
        :type polygons: List of ViewPolygon
        :param bounds: Bounding box of the text [xMin, xMax, yMin, yMax, zMin, zMax]
        :type bounds: float[6]
        :param material_name: name of the material that is set to this text
        :type material_name: str
        """
        self.polygons = polygons
        self.material_name = material_name
        # Bounding box [xMin, xMax, yMin, yMax, zMin, zMax] 
        # - NOT PRECISE, APPROXIMATED FOR OPTIMIZATION
        self.bounds = bounds

    def to_svg(self, precision):
        """Converts this viewport object to svg formatted string

        :param precision: Number of decimal places for coordinates (1-15)
        :type precision: int
        :return: String in svg format defining the ViewTextCurve
        :rtype: str
        """
        text_string = f"  <g"

        text_string += f" class=\"{self.material_name}\" >\n"

        # Converts every individual polygon
        for polygon in self.polygons:
            text_string += polygon.to_svg_shape_only(precision)

        text_string += f"  </g>\n"

        return text_string

    def get_depth(self, option):
        """Gets depth of this element based on its bounding box

        :param option: 1 for zMin, 2 for zMax, 3 for zMiddle
        :type option: int
        """
        if option == 1:
            return self.bounds[4]
        elif option == 2:
            return self.bounds[5]
        elif option == 3:
            return (self.bounds[4] + self.bounds[5]) / 2.0
        else:
            raise TypeError("Invalid sorting option")

""" Currently unused
class ViewImage(ViewType):
    Class representing an image in viewport
    

    def __init__(self, path, width, height, opacity, bounds):
        

        self.path = path
        self.width = float(width)
        self.height = float(height)
        self.opacity = opacity
        # Bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        self.bounds = bounds
        bounds[0] = bounds[0] - self.width / 2.0
        bounds[1] = bounds[1] + self.width / 2.0
        bounds[2] = bounds[2] - self.height / 2.0
        bounds[3] = bounds[3] + self.height / 2.0

        # Resizes to fit into bounding box
        if width > height:
            self.width = self.bounds[1] - self.bounds[0]
            self.height = (self.width / float(width)) * float(height)
        else:
            self.height = self.bounds[3] - self.bounds[2]
            self.width = (self.height / float(height)) * float(width)
        
    def to_svg(self, precision):
        Converts this viewport object to svg formatted string

        :param precision: Number of decimal places for coordinates (1-15)
        :type precision: int
        :return: String in svg format defining the ViewImage
        :rtype: str
        

        image_string = f"   <image href=\"{self.path}\" x=\"{round(self.bounds[0], precision)}\""\
                       f" y=\"{round(self.bounds[2], precision)}\" opacity=\"{self.opacity}\""\
                       f" width=\"{self.width}\" height=\"{self.height}\"/>\n"

        return image_string

    def get_depth(self, option):
        Gets depth of this element based on its bounding box

        :param option: 1 for zMin, 2 for zMax, 3 for zMiddle
        :type option: int
        
        if option == 1:
            return self.bounds[4]
        elif option == 2:
            return self.bounds[5]
        elif option == 3:
            return (self.bounds[4] + self.bounds[5]) / 2.0
        else:
            raise TypeError("Invalid sorting option")
"""
            
#
# CAMERAINFO TYPE
#

class CameraInfo:
    """Class representing a camera encapsulating all necessary context data 
    for the entire conversion. Its main purpose is to avoid passing or accessing 
    bpy.context throughout the entire code
    """

    def __init__(self, name, object_list, camera_pos, camera_dir, 
                 view_height, view_width, view_rot, 
                 world_to_viewport, light_pos, light_dir, 
                 depsgraph, frame_number, is_viewport):
        """Constructor of the CameraInfo type

        :param name: Name of the camera
        :type name: str
        :param object_list: List of objects to be converted using this camera
        :type object_list: List of bpy.types.Object
        :param camera_pos: Position of the camera in world coordinates
        :type camera_pos: float[3]
        :param camera_dir: Direction of the camera in world coordinates
        :type camera_dir: float[3]
        :param view_height: Height of the camera's viewport
        :type view_height: int
        :param view_width: Width of the camera's viewport
        :type view_width: int
        :param view_rot: Rotation of the camera's view (as quaternion)
        :type view_rot: float[4]
        :param world_to_viewport: Reference to a function for converting world position to viewport
        :type world_to_viewport: Reference to a function: x(coords : float[3]) : float[3]
        :param light_pos: Position of point light source in world coordinates
        :type light_pos: float[3]
        :param light_dir: Direction of planar light source from camera's view
        :type light_dir: float[3]
        :param depsgraph: Dependancy graph of the scene
        :type depsgraph: bpy.types.Depsgraph
        :param frame_number: Number of the frame this camera is exporting 
        (currently used only for GPencils)
        :type frame_number: int
        :param is_viewport: True if this camera represents the 3D view of the user, 
        False if it represents a camera object
        :type is_viewport: bool
        """
        self.name = name
        self.object_list = object_list
        self.camera_pos = camera_pos
        self.camera_dir = camera_dir
        self.view_height = view_height
        self.view_width = view_width
        self.view_rot = view_rot
        self.world_to_viewport = world_to_viewport
        self.light_dir = light_dir
        self.light_pos = light_pos
        self.depsgraph = depsgraph
        self.frame_number = frame_number
        self.is_viewport = is_viewport

    @staticmethod
    def view_to_camerainfo(context, object_list):
        """Generates a new CameraInfo instance from the current 3D view context and returns it

        :param context: context
        :type context: bpy.context
        :param object_list: List of objects used in the conversion process
        :type object_list: List of bpy.types.Object
        :return: CameraInfo instance representing 3D viewport
        :rtype: CameraInfo
        """
        props = context.scene.export_properties

        name = "viewport"

        camera_pos = view3d_utils.region_2d_to_origin_3d(bpy.context.region,
                                                         context.space_data.region_3d,
                                                         (context.region.width / 2,
                                                          context.region.height / 2))
        camera_dir = Vector(context.space_data.region_3d.view_location - camera_pos)
        camera_dir.normalize()

        view_height = context.region.height
        view_width = context.region.width

        view_rot = context.space_data.region_3d.view_rotation

        # Saves the world_to_viewport conversion function as a partial function where all arguments
        # except the 3D point position are already filled
        world_to_viewport = functools.partial(view3d_utils.location_3d_to_region_2d,
                                              context.region, context.space_data.region_3d)

        light_pos = camera_pos
        if not props.camera_light and EnumPropertyDictionaries.light_source[props.light_type] == 0:
            light_pos = props.selected_point_light.location

        light_dir = Vector((0, 0, 0))
        if EnumPropertyDictionaries.light_source[props.light_type] == 1:
            light_dir = Vector((props.light_direction[0],
                                 props.light_direction[1],
                                 props.light_direction[2]))
            light_dir.rotate(context.space_data.region_3d.view_rotation)
        
        # For evaluation
        depsgraph = context.evaluated_depsgraph_get()
        frame_number = context.scene.frame_current

        camera_info = CameraInfo(name, object_list, camera_pos, camera_dir, 
                                 view_height, view_width, view_rot, 
                                 world_to_viewport, light_pos, light_dir, 
                                 depsgraph, frame_number, True)
        
        #camera_info.region = context.region
        #camera_info.region_3d = context.space_data.region_3d

        return camera_info
    
    @staticmethod
    def camera_object_to_camerainfo(context, obj, object_list, camera_id):
        """Generates a new CameraInfo instance from a camera object and returns it

        :param context: context
        :type context: bpy.context
        :param obj: Object of type CAMERA
        :type obj: bpy.types.Object
        :param object_list: List of objects used in the conversion process
        :type object_list: List of bpy.types.Object
        :param camera_id: Unique camera identifier
        :type camera_id: int
        :return: CameraInfo instance representing 3D viewport
        :rtype: CameraInfo
        """

        props = context.scene.export_properties

        name = CAMERA_PREFIX + obj.name
        if not check_valid_file_name(name):
            name = RENAMED_CAMERA_PREFIX + str(camera_id)

        camera_pos = obj.location
        camera_dir = obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))

        view_height = context.scene.render.resolution_y
        view_width = context.scene.render.resolution_x

        view_rot = obj.rotation_euler.to_quaternion()

        # Saves the world_to_viewport conversion function as a partial function where all arguments
        # except the 3D point position are already filled
        # Conversion function makes the values returned by object_utils function compatible 
        # with view3d_utils function
        # by returning None if behind and scaling results with resolution of the camera
        def conversion(coords):
            coords2d = object_utils.world_to_camera_view(context.scene, obj, coords)
            if coords2d[2] <= 0.0:
                return None
            return Vector((coords2d[0] * view_width, coords2d[1] * view_height))

        world_to_viewport = conversion

        light_pos = camera_pos
        if not props.camera_light and EnumPropertyDictionaries.light_source[props.light_type] == 0:
            light_pos = props.selected_point_light.location

        light_dir = Vector((0, 0, 0))
        if EnumPropertyDictionaries.light_source[props.light_type] == 1:
            if props.relative_planar_light:
                light_dir = Vector((props.light_direction[0],
                                    props.light_direction[1],
                                    props.light_direction[2]))
                light_dir.rotate(view_rot)
            else:
                light_dir = Vector((props.light_direction[0],
                                    props.light_direction[1],
                                    props.light_direction[2]))
                light_dir.rotate(context.space_data.region_3d.view_rotation)

        # For evaluation
        depsgraph = context.evaluated_depsgraph_get()
        frame_number = context.scene.frame_current

        camera_info = CameraInfo(name, object_list, camera_pos, camera_dir, 
                                 view_height, view_width, view_rot, 
                                 world_to_viewport, light_pos, light_dir, 
                                 depsgraph, frame_number, False)

        #camera_info.scene = context.scene
        #camera_info.obj = obj

        return camera_info
        
#
# CLIPPING
#

# Currently unused, polygons are no longer clipped by the plugin, 
# instead they are clipped by the <svg> borders
# Several methods are still used in DepthSorter for some of the cutting methods
# and in MeshConverter for clipping parts of polygons behind the camera
class ViewPortClipping:
    """Class containing methods for polygon clipping
    """
    @staticmethod
    def is_inside(x0, y0, x1, y1, pos_x, pos_y):
        """Checks if a point is inside a rectangular boundary

        :param x0: X position of the upper left corner of the boundary
        :type x0: float
        :param y0: Y position of the upper left corner of the boundary
        :type y0: float
        :param x1: X position of the bottom right corner of the boundary
        :type x1: float
        :param y1: Y position of the bottom right corner of the boundary
        :type y1: float
        :param pos_x: X position of the point
        :type pos_x: float
        :param pos_y: Y position of the point
        :type pos_y: float
        :return: True if inside, False otherwise
        :rtype: bool
        """
        if pos_x < x0 or pos_x > x1 or pos_y < y0 or pos_y > y1:
            return False
        return True

    @staticmethod
    def intersect_on_x(x_val, vert0, vert1):
        """Calculates intersection point of a line and another vertical line

        :param x_val: X coordinate of all the points on the vertical line
        :type x_val: float
        :param vert0: Point A of the non-vertical line
        :type vert0: float[3]
        :param vert1: Point B of the non-vertical line
        :type vert1: float[3]
        :return: Vert - intersection of both lines
        :rtype: float[3]
        """
        k_y = (vert1[1] - vert0[1]) / (vert1[0] - vert0[0])
        k_depth = (vert1[2] - vert0[2]) / (vert1[0] - vert0[0])
        return (x_val,
                vert0[1] + (x_val - vert0[0]) * k_y,
                vert0[2] + (x_val - vert0[0]) * k_depth)

    @staticmethod
    def intersect_on_y(y_val, vert0, vert1):
        """Calculates intersection point of a line and another horizontal line

        :param y_val: Y coordinate of all the points on the horizontal line
        :type y_val: float
        :param vert0: Point A of the non-horizontal line
        :type vert0: float[3]
        :param vert1: Point B of the non-horizontal line
        :type vert1: float[3]
        :return: Vert - intersection of both lines
        :rtype: float[3]
        """
        k_x = (vert1[0] - vert0[0]) / (vert1[1] - vert0[1])
        k_depth = (vert1[2] - vert0[2]) / (vert1[1] - vert0[1])
        return (vert0[0] + (y_val - vert0[1]) * k_x,
                y_val,
                vert0[2] + (y_val - vert0[1]) * k_depth)

    @staticmethod
    def intersect_on_z(z_val, vert0, vert1):
        """Calculates intersection point of a line and another z line

        :param z_val: Z coordinate of all the points on the z line
        :type z_val: float
        :param vert0: Point A of the non-z line
        :type vert0: float[3]
        :param vert1: Point B of the non-z line
        :type vert1: float[3]
        :return: Vert - intersection of both lines
        :rtype: float[3]
        """
        k_x = (vert1[0] - vert0[0]) / (vert1[2] - vert0[2])
        k_y = (vert1[1] - vert0[1]) / (vert1[2] - vert0[2])
        return (vert0[0] + (z_val - vert0[2]) * k_x,
                vert0[1] + (z_val - vert0[2]) * k_y,
                z_val)

    @staticmethod
    def clip_to_boundary(min_x, min_y, max_x, max_y, verts_2d):
        """Clips a polygon using all edges of a rectangular boundary

        :param min_x: Minimum x position value
        :type min_x: float
        :param min_y: Minimum y position value
        :type min_y: float
        :param max_x: Maximum x position value
        :type max_x: float
        :param max_y: Maximum y position value
        :type max_y: float
        :param verts_2d: Unclipped polygon vertices of the viewport polygon
        :type verts_2d: list of float[3]
        :return: Clipped polygon vertices of the viewport polygon or None
        :rtype: list of float[3] or None
        """
        clipped_verts_2d = []

        # Clips using min_x
        for index, vert in enumerate(verts_2d):
            next_vert = verts_2d[(index + 1) % len(verts_2d)]
            x0 = vert[0]
            x1 = next_vert[0]
            if x0 >= min_x and x1 >= min_x:
                clipped_verts_2d.append(next_vert)
            elif x0 < min_x and x1 >= min_x:
                clipped_verts_2d.append(ViewPortClipping.intersect_on_x(min_x, vert, next_vert))
                clipped_verts_2d.append(next_vert)
            elif x0 >= min_x and x1 < min_x:
                clipped_verts_2d.append(ViewPortClipping.intersect_on_x(min_x, vert, next_vert))
        verts_2d = clipped_verts_2d
        clipped_verts_2d = []

        # Clips using min_y
        for index, vert in enumerate(verts_2d):
            next_vert = verts_2d[(index + 1) % len(verts_2d)]
            y0 = vert[1]
            y1 = next_vert[1]
            if y0 >= min_y and y1 >= min_y:
                clipped_verts_2d.append(next_vert)
            elif y0 < min_y and y1 >= min_y:
                clipped_verts_2d.append(ViewPortClipping.intersect_on_y(min_y, vert, next_vert))
                clipped_verts_2d.append(next_vert)
            elif y0 >= min_y and y1 < min_y:
                clipped_verts_2d.append(ViewPortClipping.intersect_on_y(min_y, vert, next_vert))
        verts_2d = clipped_verts_2d
        clipped_verts_2d = []

        # Clips using max_x
        for index, vert in enumerate(verts_2d):
            next_vert = verts_2d[(index + 1) % len(verts_2d)]
            x0 = vert[0]
            x1 = next_vert[0]
            if x0 <= max_x and x1 <= max_x:
                clipped_verts_2d.append(next_vert)
            elif x0 > max_x and x1 <= max_x:
                clipped_verts_2d.append(ViewPortClipping.intersect_on_x(max_x, vert, next_vert))
                clipped_verts_2d.append(next_vert)
            elif x0 <= max_x and x1 > max_x:
                clipped_verts_2d.append(ViewPortClipping.intersect_on_x(max_x, vert, next_vert))
        verts_2d = clipped_verts_2d
        clipped_verts_2d = []

        # Clips using max_y
        for index, vert in enumerate(verts_2d):
            next_vert = verts_2d[(index + 1) % len(verts_2d)]
            y0 = vert[1]
            y1 = next_vert[1]
            if y0 <= max_y and y1 <= max_y:
                clipped_verts_2d.append(next_vert)
            elif y0 > max_y and y1 <= max_y:
                clipped_verts_2d.append(ViewPortClipping.intersect_on_y(max_y, vert, next_vert))
                clipped_verts_2d.append(next_vert)
            elif y0 <= max_y and y1 > max_y:
                clipped_verts_2d.append(ViewPortClipping.intersect_on_y(max_y, vert, next_vert))

        # Returns None if no verts inside
        if len(clipped_verts_2d) < 3:
            return None

        return clipped_verts_2d

    @staticmethod
    def clip_2d_polygon(verts_2d, camera_info):
        """Returns polygon if polygon is inside viewport,
           returns None if outside viewport, returns clipped polygon if both

        :param verts_2d: Unclipped viewport polygon
        :type verts_2d: List of float[3]
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: Viewport polygon with all vertices inside the screen boundary or None
        :rtype: List of float[3] or None
        """
        res_x = camera_info.view_width
        res_y = camera_info.view_height

        # Checks visibility of 2d vertices
        all_visible = True
        for vert in verts_2d:
            if not ViewPortClipping.is_inside(0, 0, res_x, res_y, vert[0], vert[1]):
                all_visible = False

        # Returns verts if all are visible, otherwise clips
        if all_visible:
            return verts_2d
        else:
            # Clips polygon to viewport boundary
            return ViewPortClipping.clip_to_boundary(0, 0, res_x, res_y, verts_2d)

    @staticmethod
    def clip_to_front(face, camera_pos, camera_dir):
        """Creates ViewPolygon instances representing the face and camera plane,
           uses DepthSorter method to cut the face by the camera plane and returns the frontal part

        :param face: Face to cut to front
        :type face: BMFace
        :param camera_pos: Position of the camera
        :type camera_pos: float[3]
        :param camera_dir: Direction of the camera
        :type camera_dir: float[3]
        :return: Clipped part of the face in front of camera or None if the entire face is behind
        :rtype: ViewPolygon or None
        """
        # Constructs ViewPolygon instances representing the face and the camera plane
        verts = []
        for vert in face.verts:
            verts.append(vert.co)
        face_polygon = ViewPolygon(verts, 0, None, 0)

        # Other camera plane verts can be anything as long as the first one is correct
        # DepthSorter cutting function only checks the first vert and normal of the plane polygon
        camera_plane_verts = (camera_pos, (0, 0, 0), (1, 1, 1))
        camera_plane = ViewPolygon(camera_plane_verts, 0, None, 0)
        camera_plane.normal = camera_dir

        # First fragment is the front one
        fragments = DepthSorter.cut_conflicting(camera_plane, face_polygon)

        return fragments[0]

#
# CONVERSION
#

class ObjectConverter:
    """Class containing methods for converting objects into lists of ViewType instances
    """

    @staticmethod
    def convert_all_objects(props, objects, camera_info):
        """Converts all objects in a list of objects and returns ViewType lists for each type

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param objects: Objects to convert
        :type objects: List of bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: Sorted lists of ViewType instances for each type 
        (view_polygons, view_curves, view_texts, view_gpencils)
        :rtype: Tuple of (List(ViewPolygon), List(ViewCurve), List(ViewText), List(ViewCurveGroup))
        """

        # Lists of objects per each type
        meshes = []
        curves = []
        texts = []
        gpencils = []
        # images = []   Currently unused

        # Sorts objects based on their type
        for obj in objects:
            if obj.type == "MESH":
                meshes.append(obj)
            elif obj.type == "CURVE":
                curves.append(obj)
            elif obj.type == "FONT":
                texts.append(obj)
            elif obj.type == "GPENCIL":
                gpencils.append(obj)
            #elif obj.type == "EMPTY" and type(obj.data) == bpy.types.Image:
            #    images.append(obj)   Currently unused

        # Converts every type
        view_polygons = ObjectConverter.convert_all_meshes(props, meshes, camera_info)
        view_curves = ObjectConverter.convert_all_curves(props, curves, camera_info)
        view_texts = ObjectConverter.convert_all_texts(props, texts, camera_info)
        view_gpencils = ObjectConverter.convert_all_gpencils(props, gpencils, camera_info)
        #view_images = ObjectConverter.convert_all_images(props, images, camera_info)    


        # Returns as a tuple
        return (view_polygons, view_curves, view_texts, view_gpencils) #, view_images)

    @staticmethod
    def convert_all_meshes(props, objects, camera_info):
        """Converts all MESH objects in a list of objects and returns ViewPolygon list

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param objects: MESH type objects to convert
        :type objects: List of bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: List of ViewPolygon instances from all converted meshes in a scene
        :rtype: List of ViewPolygon
        """
        global STARTTIME
        STARTTIME = datetime.now()
        view_polygons = []
        view_height = camera_info.view_height
        view_width = camera_info.view_width

        # Converts all objects to ViewPolygon instances and adds them to the list
        for obj in objects:
            MeshConverter.mesh_to_view_polygons(props, obj, camera_info, view_polygons)

       
        print("Converted all meshes to view polygons... ", 
              (datetime.now() - STARTTIME).total_seconds())
        STARTTIME = datetime.now()

        # Resolves conflicts and sorts based on settings
        if not props.cut_conflicts:
            # Sorts the viewport polygons based on their depth attribute
            DepthSorter.depth_sort_bb_depth(view_polygons,
                                            props.polygon_sorting_heuristic)

            print("Quickly depth sorted... ", (datetime.now() - STARTTIME).total_seconds())
            STARTTIME = datetime.now()
        else:
            # Corrects normals of polygons so that all face the camera
            DepthSorter.correct_normals(view_polygons, (view_width / 2.0,
                                                        view_height / 2.0,
                                                        0))

            # Cuts polygons based on the chosen algorithm
            if props.cutting_algorithm == "cut.bsp":
                # BSP tree sort
                root = DepthSorter.depth_sort_bsp(view_polygons,
                        props.partition_cycles_limit)

                print("Created BSP tree... ", (datetime.now() - STARTTIME).total_seconds())
                STARTTIME = datetime.now()

                view_polygons = list()
                DepthSorter.bsp_tree_to_view_polygons(root, view_polygons,
                                                      (view_width / 2.0,
                                                       view_height / 2.0,
                                                       0))
                print("Converted BSP tree to polygon list... ", 
                      (datetime.now() - STARTTIME).total_seconds())
                STARTTIME = datetime.now()

        return view_polygons

    @staticmethod
    def convert_all_curves(props, objects, camera_info):
        """Converts all CURVE objects in a list of objects and returns sorted ViewCurve list

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param objects: CURVE type objects to convert
        :type objects: List of bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: List of ViewCurve instances from all converted curves
        :rtype: List of ViewCurve
        """
        view_curves = []

        # Converts all splines into ViewCurve instances
        for obj in objects:
            CurveConverter.curve_to_view_curves(props, obj, camera_info, view_curves)
                    
        # Depth sorts based on selected option
        sort_option = EnumPropertyDictionaries.global_sorting[props.global_sorting_option]
        view_curves.sort(key = lambda element: element.get_depth(sort_option), reverse = True)

        return view_curves

    @staticmethod
    def convert_all_texts(props, objects, camera_info):
        """Converts all FONT objects in a list of objects and returns 
        ViewText/TextCurve/TextMesh list

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param objects: FONT type objects to convert
        :type objects: List of bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: List of ViewText/ViewTextCurve/ViewTextMesh instances from all converted texts
        :rtype: List of ViewText/ViewTextCurve/ViewTextMesh
        """
        # Reads options
        global_option = EnumPropertyDictionaries.text_options[props.text_conversion]
        global_rotate = (global_option == 2 or global_option == 4)

        view_texts = []

        # Converts all selected objects of type FONT in a scene into 
        # ViewText/ViewTextCurve/ViewTextMesh instances
        for obj in objects:
            TextConverter.text_to_view_type(props, obj, camera_info, view_texts,
                                            global_option, global_rotate)

        # Depth sorts based on selected option
        sort_option = EnumPropertyDictionaries.global_sorting[props.global_sorting_option]
        view_texts.sort(key = lambda element: element.get_depth(sort_option), reverse = True)
        
        return view_texts
        
    @staticmethod
    def convert_all_gpencils(props, objects, camera_info):
        """Converts all GPENCIL objects in a list of objects and returns sorted ViewCurve list

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param objects: GPENCIL type objects to convert
        :type objects: List of bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: List of ViewCurve instances from all converted grease pencils
        :rtype: List of ViewCurve
        """
        view_gpencils = []

        # Converts all splines into ViewCurve instances
        for obj in objects:
            GreasePencilConverter.gpencil_to_view_curves(props, obj, camera_info, view_gpencils)
                    
        # Depth sorts based on selected option
        sort_option = EnumPropertyDictionaries.global_sorting[props.global_sorting_option]
        view_gpencils.sort(key = lambda element: element.get_depth(sort_option), reverse = True)

        return view_gpencils
    
    """   Currently unused
    @staticmethod
    def convert_all_images(props, objects, camera_info):
        Converts all IMAGE objects in a list of objects and returns sorted ViewImage list

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param objects: EMPTY IMAGE type objects to convert
        :type objects: List of bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: List of ViewImage instances from all converted images
        :rtype: List of ViewImage
        
        images = []

        # Converts all selected images
        for obj in objects:
            new_image = ImageConverter.image_to_view_image(props, obj, camera_info)
            if new_image is not None:
                images.append(new_image)

        # Depth sorts based on selected option
        sort_option = EnumPropertyDictionaries.global_sorting[props.global_sorting_option]
        images.sort(key = lambda element: element.get_depth(sort_option), reverse = True)

        return images
    """

class MeshConverter:
    """Class containing methods for converting meshes into a series of ViewPolygon instances
    """

    @staticmethod
    def is_backface(face, face_normal, camera_pos):
        """Checks if face is a backface

        :param face: Face of the mesh
        :type face: BMFace
        :param face_normal: Normal of the face in world coordinates (NOT LOCAL COORDINATES)
        :type face_normal: float[3]
        :param camera_pos: Position of the camera in world coordinates
        :type camera_pos: float[3]
        :return: True if backface, false otherwise
        :rtype: bool
        """
        # If dot product of camera to face vector and normal vector is greater than 0 => backface
        if (face.verts[0].co - camera_pos) @ face_normal >= 0:
            return True
        return False

    @staticmethod
    def get_face_color(props, face, face_normal, base_color, camera_info):
        """Calculates color of the face based on options and parameters

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param face: Face of the mesh
        :type face: BMFace
        :param face_normal: Normal of the face in world coordinates (NOT LOCAL COORDINATES)
        :type face_normal: float[3]
        :param face_material: Base color of the material
        :type face_material: float[4]
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: Final color as (r, g, b, opacity), rgb as (0-255), opacity as (0.0-1.0)
        :rtype: float[4]
        """
        # Gets the angle between direction to the light and face normal
        dir_vec = camera_info.light_dir
        if EnumPropertyDictionaries.light_source[props.light_type] == 0:
            dir_vec = camera_info.light_pos - face.verts[0].co

        cosine = ((dir_vec @ face_normal) /
                  (numpy.linalg.norm(dir_vec)) * numpy.linalg.norm(face_normal))

        

        light_color = props.light_color
        light_ambient = props.ambient_color

        brightness = max(cosine, 0)
        diff_color = base_color
        return  (diff_color[0] * light_ambient[0] + diff_color[0] * brightness * light_color[0],
                diff_color[1] * light_ambient[1] + diff_color[1] * brightness * light_color[1],
                diff_color[2] * light_ambient[2] + diff_color[2] * brightness * light_color[2],
                diff_color[3])

    @staticmethod
    def mesh_shape_to_view_polygon(props, face, camera_info):
        """Converts a mesh face to the ViewPolygon class with black color and 
        does NOT set bounds by default
        (lightweight compared to full conversion)

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param face: Face to convert
        :type face: BMFace
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: ViewPolygon instance representing the shape of the face in viewport
        :rtype: ViewPolygon
        """
        camera_pos = camera_info.camera_pos
        camera_dir = camera_info.camera_dir
        view_height = camera_info.view_height
        world_to_viewport = camera_info.world_to_viewport

        # Gets viewport position and depth of all vertices
        verts_2d = []
        behind_flag = False
        for vert in face.verts:
            vert_loc = world_to_viewport(vert.co)
            # If vertex is behind the camera, sets the flag and breaks the cycle
            if vert_loc is None:
                behind_flag = True
                break

            vert_depth = distance_point_to_plane(vert.co, camera_pos, camera_dir)

            verts_2d.append((vert_loc[0],
                             view_height - vert_loc[1],
                             vert_depth))

        # If vertex was behind the camera, clips the polygon to front and repeats the process
        if behind_flag:
            # Clips the face to front, RESULT IS A VIEWPOLYGON, NOT A FACE
            front_clipped_polygon = ViewPortClipping.clip_to_front(face, camera_pos, camera_dir)
            # If no part of the polygon remains in front, face is ignored
            if front_clipped_polygon is None:
                return None
            verts_2d.clear()
            for vert in front_clipped_polygon.verts:
                vert_loc = world_to_viewport(vert)
                # If vertex is behind the camera, ignores it
                if vert_loc is None:
                    continue

                vert_depth = distance_point_to_plane(vert, camera_pos, camera_dir)

                verts_2d.append((vert_loc[0],
                                view_height - vert_loc[1],
                                vert_depth))

        # Clips the 2D polygon
        verts_2d = ViewPortClipping.clip_2d_polygon(verts_2d, camera_info)
        if verts_2d is None:
            # All vertices are outside the view
            return None

        depth = distance_point_to_plane(face.calc_center_median(), camera_pos, camera_dir)

        return ViewPolygon(verts_2d,
                            depth,
                            (0, 0, 0),
                            1.0, set_bounds=False)

    @staticmethod
    def mesh_face_to_view_polygon(props, obj, face, face_normal, camera_info):
        """Converts a mesh face to the ViewPolygon class

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param obj: Object the face belongs to (required because it stores the face materials)
        :type obj: bpy.types.Object
        :param face: Face to convert
        :type face: BMFace
        :param face_normal: Normal of the face in world coordinates (NOT LOCAL COORDINATES)
        :type face_normal: float[3]
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :raises ValueError: Raised when atleast one vertex of the face is behind the camera
        :return: ViewPolygon instance representing the face in viewport
        :rtype: ViewPolygon
        """
        camera_pos = camera_info.camera_pos
        camera_dir = camera_info.camera_dir
        view_height = camera_info.view_height
        world_to_viewport = camera_info.world_to_viewport

        # Gets viewport position and depth of all vertices
        verts_2d = []
        behind_flag = False
        for vert in face.verts:
            vert_loc = world_to_viewport(vert.co)
            # If vertex is behind the camera, sets the flag and breaks the cycle
            if vert_loc is None:
                behind_flag = True
                break

            vert_depth = distance_point_to_plane(vert.co, camera_pos, camera_dir)

            verts_2d.append((vert_loc[0],
                             view_height - vert_loc[1],
                             vert_depth))

        # If vertex was behind the camera, clips the polygon to front and repeats the process
        if behind_flag:
            # Clips the face to front, RESULT IS A VIEWPOLYGON, NOT A FACE
            front_clipped_polygon = ViewPortClipping.clip_to_front(face, camera_pos, camera_dir)
            # If no part of the polygon remains in front, face is ignored
            if front_clipped_polygon is None:
                return None
            verts_2d.clear()
            for vert in front_clipped_polygon.verts:
                # Converts to Vector first because somewhere in DepthSorter 
                # it got converted to tuple?
                vert_loc = world_to_viewport(Vector(vert))
                # If vertex is behind the camera, ignores it
                if vert_loc is None:
                    continue

                vert_depth = distance_point_to_plane(vert, camera_pos, camera_dir)

                verts_2d.append((vert_loc[0],
                                view_height - vert_loc[1],
                                vert_depth))

        # Clips the 2D polygon - currently unused, polygons are not clipped by the plugin anymore
        """verts_2d = ViewPortClipping.clip_2d_polygon(verts_2d, camera_info)
        if verts_2d is None:
            # All vertices are outside the view
            return None"""

        # Gets material of this face or uses global settings
        face_material = None
        material_name = "export_svg_global_model_material"
        ignored_lighting = props.polygon_disable_lighting
        stroke_equals_fill = props.polygon_stroke_same_as_fill
        base_color = props.polygon_fill_color
        if (not props.polygon_override) and (len(obj.material_slots) != 0) and \
           (obj.material_slots[face.material_index].material is not None):
            face_material = obj.material_slots[face.material_index].material
            material_name = "polygon_" + camera_info.mat_rename_dict[face_material.name]
            ignored_lighting = face_material.export_svg_properties.ignore_lighting
            stroke_equals_fill = face_material.export_svg_properties.stroke_equals_fill
            base_color = face_material.export_svg_properties.fill_color

        face_color = [0, 0, 0, 0.0]
        if not ignored_lighting:
            # Calculates color of the face
            face_color = MeshConverter.get_face_color(props,
                                                      face, face_normal, base_color,
                                                      camera_info)

        depth = distance_point_to_plane(face.calc_center_median(), camera_pos, camera_dir)

        return ViewPolygon(verts_2d, depth, 
                           (face_color[0], face_color[1], face_color[2]), face_color[3], 
                           set_bounds=True, material_name=material_name, 
                           ignored_lighting=ignored_lighting, 
                           stroke_equals_fill=stroke_equals_fill)

    @staticmethod
    def mesh_to_view_polygons(props, obj, camera_info, view_polygons):
        """Converts the object into ViewPolygon instances and appends them to view_polygons

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param obj: Object to convert
        :type obj: bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :param view_polygons: Existing list of ViewPolygon instances to append new instances to
        :type view_polygons: List of ViewPolygon
        :raises ValueError: Raised at the end if any vertex of the object was behind the camera
        """
        camera_pos = camera_info.camera_pos

        # Applies modifiers if active
        modify = EnumPropertyDictionaries.modifiers[props.apply_modifiers] == 1
        if modify:
            dg = camera_info.depsgraph
            obj = obj.evaluated_get(dg)

        # Creates a copy of the object's mesh
        obj_mesh = bmesh.new()
        obj_mesh.from_mesh(obj.data)
        matrix_inv_transp = obj.matrix_world.inverted().transposed().to_3x3()

        # Transforms the mesh to world coordinates using the object's world matrix
        obj_mesh.transform(obj.matrix_world)
        # Saves every face of the object as a viewpolygon to the view array
        for face in obj_mesh.faces:
            # Transforms the normal of the face from local to world coordinates
            face_normal_world = (matrix_inv_transp @ face.normal).normalized()
            if props.backface_culling and \
                MeshConverter.is_backface(face, face_normal_world, camera_pos):
                # Culls backfaces
                continue

            view_polygon = MeshConverter.mesh_face_to_view_polygon(props, obj,
                                                                   face, face_normal_world,
                                                                   camera_info)
            if view_polygon is not None:
                view_polygons.append(view_polygon)

        # Frees the copied mesh
        obj_mesh.free()

class CurveConverter:
    """Class containing methods for converting curves into a series of ViewCurve instances
    """

    @staticmethod
    def spline_to_view_curve(props, spline, world_matrix, camera_info, material = None, 
                             calc_depth = True):
        """Converts the spline into a ViewCurve instance and returns it

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param spline: Spline to convert
        :type spline: bpy.types.Spline
        :param world_matrix: World matrix used to transform the spline points
        :type world_matrix: float[4][4]
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :param material: The first material assigned to the curve (None if no material assigned)
        :type material: bpy.types.Material | None
        :param calc_depth: Calculates curve depth if True, sets depth to +/-inf if False, 
        defaults to True
        :type calc_depth: bool, optional
        :return: Curve in viewport or None
        :rtype: ViewCurve | None
        """
        bezier_points = []
        min_depth = inf
        max_depth = -inf
        view_height = camera_info.view_height
        camera_pos = camera_info.camera_pos
        camera_dir = camera_info.camera_dir
        world_to_viewport = camera_info.world_to_viewport

        # Goes through the spline and saves transformed bezier points and their handles
        for point in spline.bezier_points:
            point_loc = world_matrix @ point.co
            vert_loc = world_to_viewport(point_loc)

            handle_left = world_to_viewport(world_matrix @ point.handle_left)
            
            handle_right = world_to_viewport(world_matrix @ point.handle_right)

            # If any point or handle is behind the camera, skips current point
            if (vert_loc is None) or (handle_left is None) or (handle_right is None):
                continue

            # Calculates depth
            if calc_depth:
                point_depth = distance_point_to_plane(point_loc, camera_pos, camera_dir)
                max_depth = max(max_depth, point_depth)
                min_depth = min(min_depth, point_depth)

            transformed_bezier_point = ((handle_left[0], view_height - handle_left[1]),
                                        (handle_right[0], view_height - handle_right[1]),
                                        (vert_loc[0], view_height - vert_loc[1]))

            bezier_points.append(transformed_bezier_point)

        # If not enough points have been converted to form a curve, skips it entirely
        if len(bezier_points) < 2:
            return None

        material_name = ""
        if material is None:
            material_name = "export_svg_global_curve_material"
        else:
            material_name = camera_info.mat_rename_dict[material.name]

        # Sets bounds (first 4 coords are currently unused and defaulted to 0)
        bounds = [0, 0, 0, 0, min_depth, max_depth]

        return ViewCurve(bezier_points, spline.use_cyclic_u, material_name, bounds)
        
    @staticmethod
    def splines_to_view_curve_group(props, splines, matrix_world, camera_info, material):
        """Converts a group of splines into ViewTextCurve 
        (all splines are merged into a single <path> element)

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param spline: Splines to convert
        :type spline: List of bpy.types.Spline
        :param world_matrix: World matrix used to transform the spline points
        :type world_matrix: float[4][4]
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :param material: The first material assigned to the curve (None if no material assigned)
        :type material: bpy.types.Material | None
        :return: Group of splines in viewport represented as ViewTextCurve instance 
        or None if empty
        :rtype: ViewTextCurve | None
        """
        material_name = ""
        if material is None:
            material_name = "export_svg_global_curve_material"
        else:
            material_name = camera_info.mat_rename_dict[material.name]

        curve_group = []
        for spline in splines:
            new_curve = CurveConverter.spline_to_view_curve(props, spline, matrix_world, 
                                                            camera_info, material)
            if new_curve is None:
                continue
            else:
                curve_group.append(new_curve)
        
        # If no curve has been successfully converted, returns None
        if len(curve_group) < 1:
            return None

        # Gets viewport bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        bounds = [inf, -inf, inf, -inf, inf, -inf]
        for curve in curve_group:
            bounds[0] = min(bounds[0], curve.bounds[0])
            bounds[1] = max(bounds[1], curve.bounds[1])
            bounds[2] = min(bounds[2], curve.bounds[2])
            bounds[3] = max(bounds[3], curve.bounds[3])
            bounds[4] = min(bounds[4], curve.bounds[4])
            bounds[5] = max(bounds[5], curve.bounds[5])

        return ViewTextCurve(curve_group, bounds, material_name)

    @staticmethod
    def curve_to_view_curves(props, obj, camera_info, view_curves):
        """Converts the object into ViewCurve/ViewTextCurve instances 
        and appends them to view_curves

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param obj: Object to convert
        :type obj: bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :param view_curves: Existing list of ViewCurve/ViewTextCurve instances to 
        append new instances to
        :type view_curves: List of ViewCurve/ViewTextCurve"""
        
        global_override = props.curve_override

        # If override is active or material is missing, converts with global options
        material = None
        merge_splines = props.curve_merge_splines
        if (not global_override) and (len(obj.material_slots) > 0) and \
           (obj.material_slots[0].material is not None):
            material = obj.material_slots[0].material
            merge_splines = material.export_svg_properties.merge_splines

        # Applies modifiers if active TODO
        curve_data = obj.data
        """modify = EnumPropertyDictionaries.modifiers[props.apply_modifiers] == 1
        if modify:
            dg = camera_info.depsgraph
            obj = obj.evaluated_get(dg)
            curve_data = obj.to_curve(dg, apply_modifiers = True)
            print(curve_data.splines)
        print(curve_data.splines)"""

        # Checks the merge splines option and converts accordingly
        if not merge_splines:
            for spline in curve_data.splines:
                new_curve = CurveConverter.spline_to_view_curve(props, spline, obj.matrix_world, 
                                                                camera_info, material)
                if new_curve is None:
                    continue
                else:
                    view_curves.append(new_curve)
        else:
            new_curve = CurveConverter.splines_to_view_curve_group(props, curve_data.splines,
                                                                   obj.matrix_world, 
                                                                   camera_info, material)
            if new_curve is None:
                pass
            else:
                view_curves.append(new_curve)

        """if modify:
            obj.to_curve_clear()"""
 
class TextConverter:
    """Class containing methods for converting text into a series of ViewText instances
    """

    @staticmethod
    def text_to_view_text(props, obj, camera_info, material = None):
        """Converts the object into a ViewText instance and returns it

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param obj: Object to convert
        :type obj: bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :param material: The first material assigned to the text (None if no material assigned)
        :type material: bpy.types.Material | None
        :return: Text in viewport
        :rtype: ViewText
        """
        # Gets the text content
        content = obj.data.body
        viewport_height = camera_info.view_height
        camera_pos = camera_info.camera_pos
        camera_dir = camera_info.camera_dir
        world_to_viewport = camera_info.world_to_viewport
        world_matrix = obj.matrix_world

        # Gets viewport bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        bounds = [inf, -inf, inf, -inf, inf, -inf]
        
        for vert in obj.bound_box:
            vert_loc = world_matrix @ Vector(vert)
            viewport_vert = world_to_viewport(vert_loc)
            # If any vert is behind the camera, text is skipped
            if viewport_vert is None:
                return None
            
            vert_depth = distance_point_to_plane(vert_loc, camera_pos, camera_dir)

            bounds[0] = min(bounds[0], viewport_vert[0])
            bounds[1] = max(bounds[1], viewport_vert[0])
            bounds[2] = min(bounds[2], viewport_height - viewport_vert[1])
            bounds[3] = max(bounds[3], viewport_height - viewport_vert[1])
            bounds[4] = min(bounds[4], vert_depth)
            bounds[5] = max(bounds[5], vert_depth)
        
        # Gets attributes
        material_name = ""
        if material is None:
            material_name = "export_svg_global_text_material"
        else:
            material_name = camera_info.mat_rename_dict[material.name]

        return ViewText(content, bounds, material_name)

    @staticmethod
    def text_to_view_curves(props, obj, camera_info, rotate, material):
        """Converts the object into a ViewTextCurve instance (containing list of curves) 
        and returns it

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param obj: Object to convert
        :type obj: bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :param rotate: Specifies whether the text should be rotated to face the camera
        :type rotate: bool
        :param material: The first material assigned to the text (None if no material assigned)
        :type material: bpy.types.Material | None
        :return: Text in viewport represented as ViewTextCurve instance
        :rtype: ViewTextCurve
        """
        curves = []

        matrix_world = obj.matrix_world

        if rotate:
            # Rotates the object world matrix to face the camera
            matrix_world = (Matrix.Translation(matrix_world.to_translation()) @
                            camera_info.view_rot.to_matrix().to_4x4() @
                            Matrix.Diagonal(matrix_world.to_scale()).to_4x4())

        depsgraph = camera_info.depsgraph
        curve = obj.to_curve(depsgraph)

        # Converts all splines (letters) to ViewCurve instances
        for spline in curve.splines:
            new_curve = CurveConverter.spline_to_view_curve(props, spline, matrix_world, 
                                                            camera_info)
            if new_curve is not None:
                curves.append(new_curve)

        obj.to_curve_clear()

        # Gets attributes
        material_name = ""
        if material is None:
            material_name = "export_svg_global_text_material"
        else:
            material_name = camera_info.mat_rename_dict[material.name]

        """# Sets attributes to the group according to selected text options
        stroke_color = props.text_stroke_color[0:3]
        stroke_opacity = props.text_stroke_color[3]
        fill_color = props.text_fill_color[0:3]
        fill_opacity = props.text_fill_color[3]
        stroke_width = props.text_stroke_width"""

        # Gets viewport bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        bounds = [inf, -inf, inf, -inf, inf, -inf]
        for curve in curves:
            bounds[0] = min(bounds[0], curve.bounds[0])
            bounds[1] = max(bounds[1], curve.bounds[1])
            bounds[2] = min(bounds[2], curve.bounds[2])
            bounds[3] = max(bounds[3], curve.bounds[3])
            bounds[4] = min(bounds[4], curve.bounds[4])
            bounds[5] = max(bounds[5], curve.bounds[5])

        return ViewTextCurve(curves, bounds, material_name)

    @staticmethod 
    def text_to_view_polygons(props, obj, camera_info, rotate, material):
        """Converts the object into a ViewTextMesh instance (containing list of polygons) 
        and returns it

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param obj: Object to convert
        :type obj: bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :param rotate: Specifies whether the text should be rotated to face the camera
        :type rotate: bool
        :param material: The first material assigned to the text (None if no material assigned)
        :type material: bpy.types.Material | None
        :return: Text in viewport represented as ViewTextMesh instance
        :rtype: ViewTextMesh
        """
        polygons = []

        matrix_world = obj.matrix_world

        if rotate:
            # Rotates the object world matrix to face the camera
            matrix_world = (Matrix.Translation(matrix_world.to_translation()) @
                            camera_info.view_rot.to_matrix().to_4x4() @
                            Matrix.Diagonal(matrix_world.to_scale()).to_4x4())

        # Creates a bmesh from a mesh conversion copy of the text object 
        # and transforms it into view
        obj_mesh = bmesh.new()
        obj_mesh.from_mesh(obj.to_mesh())
        obj_mesh.transform(matrix_world)

        # Saves every face of the bmesh as a viewpolygon to the list
        for face in obj_mesh.faces:
            # Transforms the normal of the face from local to world coordinates
            view_polygon = MeshConverter.mesh_shape_to_view_polygon(props, face, camera_info)
            if view_polygon is not None:
                polygons.append(view_polygon)
        obj.to_mesh_clear()

        # Gets attributes
        material_name = ""
        if material is None:
            material_name = "export_svg_global_text_material"
        else:
            material_name = camera_info.mat_rename_dict[material.name]
        
        """# Sets attributes to the group according to selected text options
        stroke_color = props.text_stroke_color[0:3]
        stroke_opacity = props.text_stroke_color[3]
        fill_color = props.text_fill_color[0:3]
        fill_opacity = props.text_fill_color[3]"""

        # Gets viewport bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        # For optimization, only checks the first and last polygon
        bounds = [inf, -inf, inf, -inf, inf, -inf]
        if len(polygons) > 0:
            ViewPolygon.recalculate_bounds(polygons[0])
            ViewPolygon.recalculate_bounds(polygons[-1])
            for polygon in [polygons[0], polygons[-1]]:
                bounds[0] = min(bounds[0], polygon.bounds[0])
                bounds[1] = max(bounds[1], polygon.bounds[1])
                bounds[2] = min(bounds[2], polygon.bounds[2])
                bounds[3] = max(bounds[3], polygon.bounds[3])
                bounds[4] = min(bounds[4], polygon.bounds[4])
                bounds[5] = max(bounds[5], polygon.bounds[5])

        return ViewTextMesh(polygons, bounds, material_name)

    @staticmethod
    def text_to_view_type(props, obj, camera_info, view_texts, global_option, global_rotate):
        """Converts the object into ViewText/ViewTextCurve/ViewTextMesh instances 
        and appends them to view_texts

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param obj: Object to convert
        :type obj: bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :param view_curves: Existing list of ViewText/ViewTextCurve/ViewTextMesh instances to 
        append new instances to
        :type view_curves: List of ViewText/ViewTextCurve/ViewTextMesh
        :param global_option: Specifies how the text should be converted (global setting)
        :type global_option: int
        :param global_rotate: Specifies whether the text should be rotated to face the camera 
        (global setting)
        :type rotate: bool"""

        # If override is active or material is missing, converts with global options
        global_override = props.text_override
        rotate = global_rotate
        option = global_option
        
        material = None
        if (not global_override) and (len(obj.material_slots) > 0) and \
           (obj.material_slots[0].material is not None):
            material = obj.material_slots[0].material
            mat_props = material.export_svg_properties

            # Reads options
            option = EnumPropertyDictionaries.text_options[mat_props.text_conversion]
            rotate = (option == 2 or option == 4)

        new_text = None
        if option == 0:
            new_text = TextConverter.text_to_view_text(props, obj, camera_info, material)
        elif option == 1 or option == 2:
            new_text = TextConverter.text_to_view_curves(props, obj, camera_info, rotate, material)
        elif option == 3 or option == 4:
            new_text = TextConverter.text_to_view_polygons(props, obj, camera_info, rotate, 
                                                           material)
        if new_text is not None:
            view_texts.append(new_text)

class GreasePencilConverter:
    """Class containing methods for converting grease pencils into ViewCurveGroup instances
    """

    @staticmethod
    def gpencil_stroke_to_view_curve(props, stroke, world_matrix, material_slots, camera_info):
        """Converts the stroke of a GP object into a ViewCurve instance

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param stroke: Stroke of the GP object
        :type stroke: bpy.types.GPencilStroke
        :param world_matrix: World matrix used to transform the spline points
        :type world_matrix: float[4][4]
        :param material_slots: Material slots of the GP object
        :type material_slots: Collection of bpy.types.MaterialSlot
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: Curve in viewport or None
        :rtype: ViewCurve | None
        """
        bezier_points = []
        min_depth = inf
        max_depth = -inf
        view_height = camera_info.view_height
        camera_pos = camera_info.camera_pos
        camera_dir = camera_info.camera_dir
        world_to_viewport = camera_info.world_to_viewport

        # Goes through the stroke points and saves transformed points
        for point in stroke.points:
            point_loc = world_matrix @ point.co
            vert_loc = world_to_viewport(point_loc)

            # If any point is behind the camera, skips current point
            if (vert_loc is None):
                continue

            # Calculates depth
            point_depth = distance_point_to_plane(point_loc, camera_pos, camera_dir)
            max_depth = max(max_depth, point_depth)
            min_depth = min(min_depth, point_depth)

            transformed_bezier_point = (None,
                                        None,
                                        (vert_loc[0], view_height - vert_loc[1]))

            bezier_points.append(transformed_bezier_point)

        # If not enough points have been converted to form a curve, skips it entirely
        if len(bezier_points) < 2:
            return None

        material_name = "export_svg_global_curve_material"
        if (not props.curve_override) and (len(material_slots) != 0) and \
           (material_slots[stroke.material_index].material is not None):
            material = material_slots[stroke.material_index].material
            material_name = camera_info.mat_rename_dict[material.name]

        # Sets bounds (first 4 coords are currently unused and defaulted to 0)
        bounds = [0, 0, 0, 0, min_depth, max_depth]

        return ViewCurve(bezier_points, stroke.use_cyclic, material_name, bounds, curved=False)

    @staticmethod
    def gpencil_layer_to_view_curves(props, layer, matrix_world, material_slots, camera_info):
        """Converts the layer of a GP object into a series of ViewCurve instances

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param layer: Layer of the GP object
        :type layer: bpy.types.GreasePencilLayer
        :param world_matrix: World matrix used to transform the spline points
        :type world_matrix: float[4][4]
        :param material_slots: Material slots of the GP object
        :type material_slots: Collection of bpy.types.MaterialSlot
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: Curves in viewport
        :rtype: List of ViewCurve
        """

        view_curves = []
        if len(layer.frames) < 1:
            return []

        scene_frame_number = camera_info.frame_number
        # Finds the currently active GPencil frame
        active_frame = layer.frames[0]
        for frame in layer.frames:
            if scene_frame_number >= frame.frame_number:
                active_frame = frame
            else:
                break

        # Converts every stroke of the 0th frame of the layer
        for stroke in active_frame.strokes:
            new_curve = GreasePencilConverter.gpencil_stroke_to_view_curve(props, stroke, 
                                                                           matrix_world, 
                                                                           material_slots, 
                                                                           camera_info)
            if new_curve is not None:
                view_curves.append(new_curve)

        return view_curves

    @staticmethod
    def gpencil_to_view_curves(props, obj, camera_info, view_curves):
        """Converts the object into two ViewCurveGroup instances and appends them to view_curves

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param obj: Object to convert
        :type obj: bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :param view_curves: Existing list of ViewCurve/ViewTextCurve/ViewCurveGroup instances to 
        append new instances to
        :type view_curves: List of ViewCurve/ViewTextCurve/ViewCurveGroup"""

        # Applies modifiers if active
        modify = EnumPropertyDictionaries.modifiers[props.apply_modifiers] == 1
        if modify:
            dg = camera_info.depsgraph
            obj = obj.evaluated_get(dg)

        # Converts layer by layer into curves
        layered_curves = []
        for layer in obj.data.layers:
            if not layer.hide:
                for view_curve in GreasePencilConverter\
                  .gpencil_layer_to_view_curves(props, layer, obj.matrix_world, 
                                                obj.material_slots, camera_info):
                    layered_curves.append(view_curve)
  
        new_group = ViewCurveGroup(layered_curves)

        view_curves.append(new_group)
        return

#   Currently unused
"""
class ImageConverter:
    Class containing methods for converting image into a series of ViewImage instances
    

    @staticmethod
    def image_to_view_image(props, obj, camera_info):
        Converts image object into a ViewImage instance and returns it

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param obj: Image object
        :type obj: bpy.types.Object
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: Instance of ViewImage representing the image object in viewport, 
        None if not valid image
        :rtype: ViewImage
        
        viewport_height = camera_info.view_height
        camera_pos = camera_info.camera_pos
        camera_dir = camera_info.camera_dir
        world_to_viewport = camera_info.world_to_viewport
        world_matrix = obj.matrix_world
       
        path = bpy.path.abspath(obj.data.filepath)
        size = obj.data.size

        # If images are copied, generates a new path for the image copy
        if props.copy_image_file:
            path = basename(props.output_path)
            if path[-4:] == ".svg":
                path = path[0:-4] + "_" + basename(bpy.path.abspath(obj.data.filepath))
        
        if path[-4:] != ".png" and path[-4:] != ".jpg" and path[-5:] != ".jpeg":
            return None

        if obj.data.source != "FILE" or size[0] <= 0 or size[1] <= 0:
            return None

        # Gets viewport opacity
        opacity = 1.0
        if obj.use_empty_image_alpha:
            opacity = obj.color[3]

        # Gets viewport bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        bounds = [inf, -inf, inf, -inf, inf, -inf]
        
        for vert in obj.bound_box:
            vert_loc = world_matrix @ Vector(vert)
            viewport_vert = world_to_viewport(vert_loc)
            # If any vert is behind the camera, text is skipped
            if viewport_vert is None:
                return None
            
            vert_depth = distance_point_to_plane(vert_loc, camera_pos, camera_dir)

            bounds[0] = min(bounds[0], viewport_vert[0])
            bounds[1] = max(bounds[1], viewport_vert[0])
            bounds[2] = min(bounds[2], viewport_height - viewport_vert[1])
            bounds[3] = max(bounds[3], viewport_height - viewport_vert[1])
            bounds[4] = min(bounds[4], vert_depth)
            bounds[5] = max(bounds[5], vert_depth)
        
        return ViewImage(path, size[0], size[1], opacity, bounds)
"""
        
class AnnotationConverter:
    """Class for converting annotations into two series 
    (prio and non-prio) of ViewCurveGroup instances
    """

    def ann_layer_to_svg_style(layer, class_name, grayscale = False):
        """Generates an SVG <style> string for a given annotation layer

        :param layer: Layer of the GP object
        :type layer: bpy.types.GreasePencilLayer
        :param class_name: Class name of the style element
        :type class_name: str
        :param grayscale: If true, applies grayscale filter to the class definition
        :type grayscale: bool
        :return: SVG <style> string styling the layer
        :rtype: str
        """
        style_string = ""

        style_string += f"     .{class_name} {{\n"\
                        f"          stroke-width : {layer.thickness};\n"\
                        f"          stroke : rgb({get_rgb_val_from_linear(layer.color[0])},"\
                        f"{get_rgb_val_from_linear(layer.color[1])},"\
                        f"{get_rgb_val_from_linear(layer.color[2])});\n"\
                        f"          stroke-opacity : {layer.annotation_opacity};\n"\
                        f"          fill : none;\n"
        
        if grayscale:
            style_string += f"          filter: saturate(0%);"\

        style_string += f"     }}\n\n"
     
        return style_string

    def ann_stroke_to_view_curve(props, stroke, layer_name, camera_info):
        """Converts a single GP stroke of an annotation layer into a ViewCurve instance

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param stroke: Stroke of the GP annotation
        :type stroke: bpy.types.GPencilStroke
        :param layer_name: Name of the annotation layer (used as a material/style)
        :type material_slots: str
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: Curve in viewport or None
        :rtype: ViewCurve | None
        """
        bezier_points = []
        min_depth = inf
        max_depth = -inf
        view_height = camera_info.view_height
        view_width = camera_info.view_width
        camera_pos = camera_info.camera_pos
        camera_dir = camera_info.camera_dir
        world_to_viewport = camera_info.world_to_viewport

        # Goes through the stroke points and saves points
        for point in stroke.points:

            # No transformation needed, annotation points are saved in world coordinates
            point_loc = point.co
            transformed_bezier_point = None

            # If annotation is sticked to the view, calculates differently
            if stroke.display_mode == "SCREEN":
                vert_loc = [point_loc[0] * view_width / 100.0, view_height * point_loc[1] / 100.0]
                
                max_depth = 0
                min_depth = 0

                transformed_bezier_point = (None, None, (vert_loc[0], view_height - vert_loc[1]))
            else:
                vert_loc = world_to_viewport(point_loc)

                # If any point is behind the camera, skips current point
                if (vert_loc is None):
                    continue

                point_depth = distance_point_to_plane(point_loc, camera_pos, camera_dir)
                max_depth = max(max_depth, point_depth)
                min_depth = min(min_depth, point_depth)

                transformed_bezier_point = (None, None, (vert_loc[0], view_height - vert_loc[1]))

            bezier_points.append(transformed_bezier_point)

        # If not enough points have been converted to form a curve, skips it entirely
        if len(bezier_points) < 2:
            return None

        material_name = camera_info.ann_rename_dict[layer_name]

        # Sets bounds (first 4 coords are currently unused and defaulted to 0)
        bounds = [0, 0, 0, 0, min_depth, max_depth]

        return ViewCurve(bezier_points, stroke.use_cyclic, material_name, bounds, curved=False)

    def ann_layer_to_view_curves(props, layer, camera_info):
        """Converts the layer of a GP annotation into a series of ViewCurve instances

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param layer: Layer of the GP object
        :type layer: bpy.types.GreasePencilLayer
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: Curves in viewport
        :rtype: List of ViewCurve
        """

        view_curves = []
        if len(layer.frames) < 1:
            return []

        scene_frame_number = camera_info.frame_number
        # Finds the currently active GPencil frame
        active_frame = layer.frames[0]
        for frame in layer.frames:
            if scene_frame_number >= frame.frame_number:
                active_frame = frame
            else:
                break

        # Converts every stroke of the 0th frame of the layer
        for stroke in layer.frames[0].strokes:
            new_curve = AnnotationConverter.ann_stroke_to_view_curve(props, stroke, layer.info, 
                                                                     camera_info)
            if new_curve is not None:
                view_curves.append(new_curve)

        return view_curves

    def convert_all_anns(props, datas, camera_info, priority):
        """Converts visible prio/non-prio layers of annotations into
        a series of ViewCurve instances

        :param props: Export properties
        :type props: bpy.context.scene.export_properties
        :param datas: Annotation (GPencil) data to convert
        :type datas: List of bpy.types.GreasePencil
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :param priority: If True, converts priority annotations, 
        if False, converts non-priority annotations
        :type priority: bool
        :return: Sorted list of ViewCurve instances
        :rtype: List of ViewCurve
        """
        anns = []

        for data in datas:
            if data is not None:
                for layer in data.layers:
                    if not layer.annotation_hide:
                        if (layer.show_in_front and priority) or \
                           (not layer.show_in_front and not priority):
                            view_curves = AnnotationConverter\
                                .ann_layer_to_view_curves(props, layer, camera_info)
                            for curve in view_curves:
                                anns.append(curve)

        # Depth sorts non-priority layers/curves based on selected option
        # Priority layers are not sorted, their order is based on the annotation layers order
        if not priority:
            sort_option = EnumPropertyDictionaries.global_sorting[props.global_sorting_option]
            anns.sort(key = lambda element: element.get_depth(sort_option), reverse = True)

        return anns

#
# DEPTH SORTING
#

class DepthSorter:
    """Class containing methods for depth sorting and cutting polygons
    """

    @staticmethod
    def depth_sort(view_polygons):
        """Primitive depth sorting method that sort polygons based on their depth attribute

        :param view_polygons: Polygons to sort
        :type view_polygons: List of ViewPolygon instances
        """
        view_polygons.sort(key = lambda polygon: polygon.depth, reverse = True)

    @staticmethod
    def depth_sort_bb_depth(view_polygons, sorting_heuristic):
        """Sorts polygons by primitive sort using a heuristic

        :param view_polygons: Polygons to sort
        :type view_polygons: List of ViewPolygon instances
        :param sorting_heuristic: Sorting heuristic (values defined in ExportSVGProperties)
        :type sorting_heuristic: string
        :raises TypeError: Raised when unsupported heuristic is given
        """
        sort_option = EnumPropertyDictionaries.polygon_sorting[sorting_heuristic]
        if sort_option == 1:
            view_polygons.sort(key = lambda polygon: (polygon.bounds[5] + polygon.bounds[4]) / 2.0,
                               reverse = True)
        elif sort_option == 0:
            view_polygons.sort(key = lambda polygon: polygon.bounds[4], reverse = True)
        elif sort_option == 2:
            view_polygons.sort(key = lambda polygon: polygon.bounds[5], reverse = True)
        elif sort_option == 3:
            for polygon in view_polygons:
                depth = 0
                for vert in polygon.verts:
                    depth += vert[2]
                polygon.depth = depth / len(polygon.verts)
            view_polygons.sort(key = lambda polygon: polygon.depth, reverse = True)
        else:
            raise TypeError("Invalid sorting heuristic")

    @staticmethod
    def depth_sort_bsp(view_polygons, cycle_limit):
        """Creates a BSP tree from a list of polygons and returns it's root node

        :param view_polygons: Polygons to sort
        :type view_polygons: List of ViewPolygon instances
        :param cycle_limit: Maximum number of bsp cycles
        :type cycle_limit: int
        :raises RecursionError: Raised when partition cycles limit is reached
        :return: Root node of the created BSP tree
        :rtype: BSPNode
        """
        # Creates a root node
        root = BSPNode()
        if len(view_polygons) == 0:
            return root
        else:
            root.polygon_list.append(view_polygons.pop(round(len(view_polygons) / 2)))
        root_plane = root.polygon_list[0]

        # There is only one polygon
        if len(view_polygons) == 0:
            return root

        root.is_leaf = False

        # First partition
        for i in range(len(view_polygons) - 1, -1, -1):
            pos = DepthSorter.relative_pos(root_plane, view_polygons[i])
            if pos == 1:
                if root.front_node is None:
                    root.front_node = BSPNode()
                root.front_node.polygon_list.append(view_polygons.pop(i))
            elif pos == 0:
                # Cuts in two and culls small fragments
                cut_polygons = DepthSorter.cut_conflicting(root_plane, view_polygons.pop(i))

                if cut_polygons[0] is not None:
                    if root.front_node is None:
                        root.front_node = BSPNode()
                    root.front_node.polygon_list.append(cut_polygons[0])

                if cut_polygons[1] is not None:
                    if root.back_node is None:
                        root.back_node = BSPNode()
                    root.back_node.polygon_list.append(cut_polygons[1])
            else:
                if root.back_node is None:
                    root.back_node = BSPNode()
                root.back_node.polygon_list.append(view_polygons.pop(i))

        # Initializes the leaf node list
        leaf_nodes = list()
        if root.front_node is not None:
            leaf_nodes.append(root.front_node)
        if root.back_node is not None:
            leaf_nodes.append(root.back_node)

        j = 0
        # Cycles until no further partition is possible
        while DepthSorter.bsp_partition(leaf_nodes):
            j += 1
            if j >= cycle_limit:
                raise RecursionError("Partition limit reached")
                return None
        print("Number of partition cycles: ", j)
        print("Number of leaf nodes: ", len(leaf_nodes))
        return root

    @staticmethod
    def bsp_partition(bsp_nodes):
        """Partitions all the leaf nodes and updates the list of leaf nodes

        :param bsp_nodes: List of all leaf nodes of the BSP tree (WILL GET UPDATED)
        :type bsp_nodes: List of BSPNode instances
        :return: True if the tree has been changed, False otherwise
        :rtype: bool
        """
        changed = False
        for bsp_node in bsp_nodes:
            view_polygons = bsp_node.polygon_list
            # Splits the node if it has more than one polygon
            if len(view_polygons) > 1:
                # Pops the partitioning polygon to a temp var
                part_plane = view_polygons.pop(round(len(view_polygons) / 2))

                bsp_node.is_leaf = False
                changed = True

                # Splits
                for i in range(len(view_polygons) - 1, -1, -1):
                    pos = DepthSorter.relative_pos(part_plane, view_polygons[i])

                    if pos == 1:
                        if bsp_node.front_node is None:
                            bsp_node.front_node = BSPNode()
                        bsp_node.front_node.polygon_list.append(view_polygons.pop(i))
                    elif pos == 0:
                        # Cuts in two and culls small fragments
                        cut_polygons = DepthSorter.cut_conflicting(part_plane, view_polygons.pop(i))

                        if cut_polygons[0] is not None:
                            if bsp_node.front_node is None:
                                bsp_node.front_node = BSPNode()
                            bsp_node.front_node.polygon_list.append(cut_polygons[0])

                        if cut_polygons[1] is not None:
                            if bsp_node.back_node is None:
                                bsp_node.back_node = BSPNode()
                            bsp_node.back_node.polygon_list.append(cut_polygons[1])
                    else:
                        if bsp_node.back_node is None:
                            bsp_node.back_node = BSPNode()
                        bsp_node.back_node.polygon_list.append(view_polygons.pop(i))

                # Appends the partitioning polygon back to this node
                view_polygons.append(part_plane)

        # Deletes non-leaf nodes from the list and appends new leaf nodes
        for i in range(len(bsp_nodes) - 1, -1, -1):
            node = bsp_nodes[i]
            if not node.is_leaf:
                if node.front_node is not None:
                    bsp_nodes.append(node.front_node)
                if node.back_node is not None:
                    bsp_nodes.append(node.back_node)
                del bsp_nodes[i]

        return changed

    @staticmethod
    def bsp_tree_to_view_polygons(root, view_polygons, camera_pos):
        """Recursively traverses the bsp tree and appends polygons to the final list

        :param root: Root node of the BSP tree
        :type root: BSPNode
        :param view_polygons: List that will store the final sorted polygons
        :type view_polygons: List of ViewPolygon instances
        :param camera_pos: Position of the camera in the scene
        :type camera_pos: float[3]
        """
        if root is None:
            return
        if root.is_leaf:
            view_polygons.append(root.polygon_list[0])
        else:
            # Checks if the camera is in front or back of this polygon plane
            plane_point = root.polygon_list[0].verts[0]
            dir_vector = Vector((plane_point[0] - camera_pos[0],
                                 plane_point[1] - camera_pos[1],
                                 plane_point[2] - camera_pos[2]))
            if dir_vector @ root.polygon_list[0].normal < 0:
                # In front
                DepthSorter.bsp_tree_to_view_polygons(root.back_node, view_polygons, camera_pos)
                view_polygons.append(root.polygon_list[0])
                DepthSorter.bsp_tree_to_view_polygons(root.front_node, view_polygons, camera_pos)
            else:
                # Behind
                DepthSorter.bsp_tree_to_view_polygons(root.front_node, view_polygons, camera_pos)
                view_polygons.append(root.polygon_list[0])
                DepthSorter.bsp_tree_to_view_polygons(root.back_node, view_polygons, camera_pos)


    @staticmethod
    def correct_normals(view_polygons, viewpoint_pos):
        """If viewpoint is not in front of the polygon, inverts the polygon's normal so that it is

        :param view_polygons: Polygons to correct
        :type view_polygons: List of ViewPolygon instances
        :param viewpoint_pos: Viewpoint, position of the camera
        :type viewpoint_pos: float[3]
        """
        for polygon in view_polygons:
            plane_point = polygon.verts[0]
            dir_vector = Vector((viewpoint_pos[0] - plane_point[0],
                                 viewpoint_pos[1] - plane_point[1],
                                 viewpoint_pos[2] - plane_point[2]))
            if dir_vector @ polygon.normal > 0:
                polygon.normal.negate()

    @staticmethod
    def is_fragment(view_polygon):
        """Check if polygon is a very small fragment

        :param view_polygon: Polygon to check
        :type view_polygon: ViewPolygon
        :return: True if below the cull threshold, false otherwise
        :rtype: bool
        """
        if len(view_polygon.verts) < 3:
            return True

        difference_sum = 0
        for i in range(0, len(view_polygon.verts) - 1):
            difference_sum += numpy.abs(view_polygon.verts[i][0] - view_polygon.verts[i + 1][0]) +\
                              numpy.abs(view_polygon.verts[i][1] - view_polygon.verts[i + 1][1]) +\
                              numpy.abs(view_polygon.verts[i][2] - view_polygon.verts[i + 1][2])

        # If the total sum of coordinate differences is extremely small, considers this a fragment
        if numpy.abs(difference_sum) < POLYGON_CULL_THRESHOLD:
            return True
        return False

    @staticmethod
    def vert_relative_pos(plane_polygon, vert):
        """Checks the relative position of a vert and a polygon

        :param plane_polygon: Polygon that defines the plane
        :type plane_polygon: ViewPolygon
        :param vert: Vert to check
        :type vert: float[3]
        :return: Returns -1 if behind plane, 0 if within threshold, 1 if in front of plane
        :rtype: int -1/0/1
        """
        distance = distance_point_to_plane(vert, plane_polygon.verts[0], plane_polygon.normal)
        if numpy.abs(distance) < PLANE_DISTANCE_THRESHOLD:
            return 0
        elif distance > 0:
            return 1
        else:
            return -1

    @staticmethod
    def vert_relative_pos_bool(plane_polygon, vert):
        """Checks the relative position of a vert and a polygon

        :param plane_polygon: Polygon that defines the plane
        :type plane_polygon: ViewPolygon
        :param vert: Vert to check
        :type vert: float[3]
        :return: Returns false if behind the polygon, true if in front
        :rtype: bool
        """
        plane_point = plane_polygon.verts[0]
        dir_vector = Vector((vert[0] - plane_point[0],
                             vert[1] - plane_point[1],
                             vert[2] - plane_point[2]))
        dot_product = dir_vector @ plane_polygon.normal
        if dot_product >= 0:
            return True
        else:
            return False

    @staticmethod
    def relative_pos(plane_polygon, polygon_p):
        """Checks the relative position of polygon p and a plane defined by another polygon

        :param plane_polygon: Polygon that defines the plane
        :type plane_polygon: ViewPolygon
        :param polygon_p: Polygon to check
        :type polygon_p: ViewPolygon
        :return: Returns -1 if p is behind the plane, 0 if in collision, 1 if in front
        :rtype: int -1/0/1
        """
        all_front = True
        all_back = True
        for vert in polygon_p.verts:
            vert_rel_pos = DepthSorter.vert_relative_pos(plane_polygon, vert)
            if vert_rel_pos == 1:
                all_back = False
            elif vert_rel_pos == -1:
                all_front = False

        if all_front:
            return 1
        elif all_back:
            return -1
        else:
            return 0

    @staticmethod
    def relative_pos_bool(plane_polygon, polygon_p):
        """Checks the relative position of NON-CONFLICTING polygons

        :param plane_polygon: Polygon that defines the plane
        :type plane_polygon: ViewPolygon
        :param polygon_p: Polygon to check
        :type polygon_p: ViewPolygon
        :raises TypeError: Raised if polygon_p is in conflict with plane of plane_polygon
        :return: Returns false if p is behind the plane polygon, true if in front
        :rtype: bool
        """
        all_front = True
        all_back = True
        for vert in polygon_p.verts:
            vert_rel_pos = DepthSorter.vert_relative_pos(plane_polygon, vert)
            if vert_rel_pos == 1:
                all_back = False
            elif vert_rel_pos == -1:
                all_front = False

        if all_front:
            return True
        elif all_back:
            return False
        else:
            raise TypeError("Method relative_pos_bool() got a conflict")

    @staticmethod
    def p_behind_q(polygon_p, polygon_q):
        """Checks the relative position of NON-CONFLICTING polygons

        :param polygon_p: Polygon to check
        :type polygon_p: ViewPolygon
        :param polygon_q: Polygon to check
        :type polygon_q: ViewPolygon
        :return: True if p is behind q, false otherwise
        :rtype: bool
        """
        try:
            if DepthSorter.relative_pos_bool(polygon_q, polygon_p):
                return False
            else:
                return True
        except TypeError:
            if DepthSorter.relative_pos_bool(polygon_p, polygon_q):
                return True
            else:
                return False

    @staticmethod
    def cut_conflicting(plane_polygon, polygon_p):
        """Cuts polygon p by the plane and returns tuple of two resulting fragments

        :param plane_polygon: Plane defining polygon to cut by
        :type plane_polygon: ViewPolygon
        :param polygon_p: Polygon to be cut
        :type polygon_p: ViewPolygon
        :return: Returns both fragments, None instead of a fragment if the fragment is too small
        :rtype: (ViewPolygon, ViewPolygon), where ViewPolygon can be ViewPolygon instance or None
        """
        back_pol_verts = list()
        front_pol_verts = list()
        verts = polygon_p.verts

        # Checks the last vertex first for the context
        currently_in_front = DepthSorter.vert_relative_pos_bool(plane_polygon, verts[-1])
        for i, vert in enumerate(verts):
            if DepthSorter.vert_relative_pos_bool(plane_polygon, vert):
                # If vert is in front
                if currently_in_front:
                    # And last vert was also in front, appends to front
                    front_pol_verts.append(vert)
                else:
                    # And last vert was not in front, appends intersection to both
                    # and vert to front
                    currently_in_front = True
                    next_vert = verts[(i - 1) % len(verts)]
                    # Direction of the intersection, does not cut exactly on plane but close to it
                    intersect_dir = Vector((next_vert[0] - vert[0],
                                    next_vert[1] - vert[1],
                                    next_vert[2] - vert[2])).normalized() / POLYGON_CUT_PRECISION
                    try:
                        intersect_vert = intersect_line_plane(Vector(vert),
                                                              Vector(next_vert),
                                                              plane_polygon.verts[0],
                                                              plane_polygon.normal)
                        back_pol_verts.append((intersect_vert[0] + intersect_dir[0],
                                               intersect_vert[1] + intersect_dir[1],
                                               intersect_vert[2] + intersect_dir[2]))
                        front_pol_verts.append((intersect_vert[0] - intersect_dir[0],
                                                intersect_vert[1] - intersect_dir[1],
                                                intersect_vert[2] - intersect_dir[2]))
                        front_pol_verts.append(vert)
                    except TypeError:
                        back_pol_verts.append(vert)
                        front_pol_verts.append(vert)
            else:
                # If vert is behind
                if currently_in_front:
                    # And last vert was not behind, appends intersection to both
                    # and vert to back
                    currently_in_front = False
                    next_vert = verts[(i - 1) % len(verts)]
                    # Direction of the intersection, does not cut exactly on plane but close to it
                    intersect_dir = Vector((next_vert[0] - vert[0],
                                    next_vert[1] - vert[1],
                                    next_vert[2] - vert[2])).normalized() / POLYGON_CUT_PRECISION
                    try:
                        intersect_vert = intersect_line_plane(Vector(vert),
                                                              Vector(next_vert),
                                                              plane_polygon.verts[0],
                                                              plane_polygon.normal)
                        front_pol_verts.append((intersect_vert[0] + intersect_dir[0],
                                                intersect_vert[1] + intersect_dir[1],
                                                intersect_vert[2] + intersect_dir[2]))
                        back_pol_verts.append((intersect_vert[0] - intersect_dir[0],
                                               intersect_vert[1] - intersect_dir[1],
                                               intersect_vert[2] - intersect_dir[2]))
                        back_pol_verts.append(vert)
                    except TypeError:
                        front_pol_verts.append(vert)
                        back_pol_verts.append(vert)
                else:
                    # And last vert was also behind, appends to back
                    back_pol_verts.append(vert)

        # Creates a pair of result polygons
        polygon_p.verts = front_pol_verts
        polygon_q = deepcopy(polygon_p)
        polygon_q.verts = back_pol_verts
        # Culls fragments and recalculates bounds
        if DepthSorter.is_fragment(polygon_p):
            polygon_p = None
        else:
            ViewPolygon.recalculate_bounds(polygon_p)
        if DepthSorter.is_fragment(polygon_q):
            polygon_q = None
        else:
            ViewPolygon.recalculate_bounds(polygon_q)

        return (polygon_p, polygon_q)

#
# EXPORT
#

class SVGFileGenerator:
    """Class containing methods used for generating the svg file
    """

    @staticmethod
    def get_collection_order(collection):
        """Gets collection names ordered by their appearance in the object list (recursive)

        :param collection: Root collection
        :type collection: bpy.types.Collection
        :return: List of names of all nested collections starting with 
        the name of the root collection ordered by the object list
        :rtype: List of str 
        """
        names = [collection.name]
        for child in collection.children:
            for name in SVGFileGenerator.get_collection_order(child):
                names.append(name)
        return names

    @staticmethod
    def get_material_dict(used_materials):
        """Creates dictionary of material names and their renames

        :param used_materials: _description_
        :type used_materials: _type_
        :return: Dictionary of { (material_name : css_class_name) }
        :rtype: dict
        """
        renamed_counter = 0
        names = dict()
        for material in set(used_materials):
            if material is not None:
                class_name = material.name
                if check_valid_css_name(class_name):
                    class_name = MATERIAL_PREFIX + class_name
                else:
                    class_name = RENAMED_MATERIAL_PREFIX + str(renamed_counter)
                    renamed_counter += 1
                names[material.name] = class_name
        return names

    @staticmethod
    def get_annotation_dict(used_layers):
        """Creates dictionary of annotation layer names and their renames

        :param used_layers: Layers of annotations
        :type used_layers: bpy.types.GreasePencilLayer
        :return: Dictionary of { (layer_name : css_class_name) }
        :rtype: dict
        """
        renamed_counter = 0
        names = dict()
        for layer in used_layers:
            new_name = layer.info
            if check_valid_css_name(new_name):
                new_name = ANNOTATION_PREFIX + new_name
            else:
                new_name = RENAMED_ANNOTATION_PREFIX + str(renamed_counter)
                renamed_counter += 1
            names[layer.info] = new_name
        return names

    @staticmethod
    def objects_to_svg_group(props, objects, additional_view_types, name, camera_info):
        """Generates svg <g> group from objects and returns it as string
        along with its min and max depth

        :param context: Context
        :type context: bpy.context
        :param objects: Objects to include in the group
        :type objects: List of bpy.types.Object
        :param additional_view_types: Additional ViewType objects to include and sort in this group
        :type additional_view_types: List of ViewType
        :param name: Name of the collection
        :type name: str
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: Tuple of (svg_string, z_min, z_max)
        :rtype: (str, float, float)
        """
        group_string = f" <g id=\"{name}\">\n"

        # Gets sort and precision option
        coord_precision = props.coord_precision
        sort_option = EnumPropertyDictionaries.global_sorting[props.global_sorting_option]

        # Converts all objects in a scene to sorted lists of ViewType instances
        #(view_polygons, view_curves, view_texts, view_gpencils, view_images) = \
        # ObjectConverter.convert_all_objects(props, objects, camera_info)
        (view_polygons, view_curves, view_texts, view_gpencils) = \
            ObjectConverter.convert_all_objects(props, objects, camera_info)

        # Adds all non-empty groups into the sorting queue
        # Gets min and max depth of this collection by checking
        # the first and last element of each type group
        sorting_queue = []
        z_min = inf
        z_max = -inf
        #for group in \
        # [view_polygons, view_curves, view_texts, view_gpencils, view_images, additional_view_types]:
        for group in \
            [view_polygons, view_curves, view_texts, view_gpencils, additional_view_types]:    
            if len(group) > 0:
                sorting_queue.append(group)
                z_max = max(z_max, group[0].bounds[5])
                z_min = min(z_min, group[-1].bounds[4])

        if len(sorting_queue) > 0:
            # Converts lists to deques for efficient popping
            for i in range(0, len(sorting_queue)):
                sorting_queue[i] = deque(sorting_queue[i])

            # Takes the next element with the greatest depth from any type group, 
            # writes it and removes it
            # Continues until only 1 type group remains
            while len(sorting_queue) > 1:
                next_depth = -inf
                next_group_index = 0

                # Finds group with the greatest depth of the first element
                for i, type_group in enumerate(sorting_queue):
                    el_depth = type_group[0].get_depth(sort_option)
                    if el_depth > next_depth:
                        next_depth = el_depth
                        next_group_index = i
                
                # Writes and pops that element from the group 
                # (and deletes the group if it is empty)
                group_string += sorting_queue[next_group_index].popleft().to_svg(coord_precision)
                if len(sorting_queue[next_group_index]) == 0:
                    del sorting_queue[next_group_index]

            # Writes the remaining type group in order
            for el in sorting_queue[0]:
                group_string += el.to_svg(coord_precision)

        group_string += f" </g> \n"

        return (group_string, z_min, z_max)

    @staticmethod
    def collections_to_svg_groups(context, collections, camera_info):
        """Generates svg <g> for each collection
        This method was split off from gen_svg_body() 
        therefore it accesses data in similar ways to other high-level methods

        :param context: Context
        :type context: bpy.context
        :param collections: Collections to convert - 
        list of (collection_name, list of objects in collection)
        :type collections: List of (str, List(bpy.types.Object))
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: SVG string of <g> elements for every collection
        :rtype: str
        """

        groups_string = ""
        props = context.scene.export_properties
        
        # Converts to a list of (name, svg_string, z_min, z_max) for every collection
        converted_collections = []
        renamed_counter = 0
        for name, objects in collections:
            # Renames if invalid CSS name
            col_name = COLLECTION_PREFIX + name
            if not check_valid_css_name(name):
                col_name = RENAMED_COLLECTION_PREFIX + str(renamed_counter)
                renamed_counter += 1
    
            res = SVGFileGenerator.objects_to_svg_group(props, objects, [], col_name,
                                                        camera_info)
            converted_collections.append((name, res[0], res[1], res[2]))
        

        # Sorts collections based on the selected option
        coll_sort_option = EnumPropertyDictionaries \
                            .collection_sorting[props.collection_sorting_option]
        if coll_sort_option == 3:
            # Creates a dictionary linking collection names and rank in object list
            coll_order = dict()
            for i, name in enumerate(SVGFileGenerator\
                                     .get_collection_order(context.scene.collection)):
                coll_order[name] = i
            # Sorts by the dictionary results for each name
            converted_collections.sort(key = lambda col: coll_order[col[0]], reverse = True)
        elif coll_sort_option == 0:
            converted_collections.sort(key = lambda col: col[2], reverse = True)
        elif coll_sort_option == 2:
            converted_collections.sort(key = lambda col: (col[2] + col[3]) / 2.0, reverse = True)
        else:
            converted_collections.sort(key = lambda col: col[3], reverse = True)


        # Returns concatenated <g> strings
        for col in converted_collections:
            groups_string += col[1]
        return groups_string

    @staticmethod
    def gen_svg_head(context, camera_info):
        """Generates svg head and returns it

        :param context: Context
        :type context: bpy.context
        :param camera_info: Information about the camera used to generate this file
        :type camera_info: CameraInfo
        :return: File head
        :rtype: str
        """
        props = context.scene.export_properties
        grayscale = props.grayscale
        head = f"<svg width=\"{camera_info.view_width}\" height=\"{camera_info.view_height}\"" + \
               " stroke-linejoin=\"round\"" + \
               " stroke-linecap=\"round\"" + \
               " version=\"1.1\" xmlns=\"http://www.w3.org/2000/svg\">\n\n"

        # ============ MATERIALS & ANIMATIONS & PATTERNS  =================
        # Generates styles based on used global settings and individual materials
        pattern_string = ""
        pattern_string += props.get_svg_patterns()
        style_string = "  <style>\n"
        style_string += props.polygon_properties_to_svg_style() + \
                        props.curve_properties_to_svg_style() + \
                        props.text_properties_to_svg_style()
        keyframe_string = ""
        

        used_materials = []

        # Finds all materials slotted in all selected objects that are not overridden
        for obj in camera_info.object_list:
            if (not props.polygon_override) and (obj.type == "MESH"):
                for material_slot in obj.material_slots:
                    used_materials.append(material_slot.material)
            elif (not props.curve_override) and (obj.type == "CURVE" or obj.type == "GPENCIL"):
                for material_slot in obj.material_slots:
                    used_materials.append(material_slot.material)
            elif (not props.text_override) and (obj.type == "FONT"):
                for material_slot in obj.material_slots:
                    used_materials.append(material_slot.material)

        # Creates a dictionary for renaming materials and adds it to camera info
        mat_rename_dict = SVGFileGenerator.get_material_dict(used_materials)
        camera_info.mat_rename_dict = mat_rename_dict

        # Generates style, keyframe and pattern strings for every unique material
        for material in set(used_materials):
            if material is not None:
                if material.export_svg_properties.use_pattern:
                    pattern_string += material.export_svg_properties\
                        .get_svg_pattern(mat_rename_dict[material.name] + "_pattern")
                style_string += material.export_svg_properties\
                    .to_svg_style(mat_rename_dict[material.name], material, grayscale)
                if material.export_svg_properties.enable_animations:
                    keyframe_string += material.export_svg_animation_properties\
                        .to_css_keyframes(ANIMATION_PREFIX + mat_rename_dict[material.name], 
                                          camera_info)
        
        # ============ ANNOTATIONS =================
        used_annotation_layers = []

        # Finds all visible annotation layers
        if context.annotation_data is not None:
            for layer in context.annotation_data.layers:
                if not layer.annotation_hide:
                    used_annotation_layers.append(layer)

        # Creates a dictionary for renaming annotation layers and adds it to camera_info
        ann_rename_dict = SVGFileGenerator.get_annotation_dict(used_annotation_layers)
        camera_info.ann_rename_dict = ann_rename_dict

        # Generates style string for every annotation layer
        for layer in used_annotation_layers:
            style_string += AnnotationConverter.ann_layer_to_svg_style(layer, 
                                                                       ann_rename_dict[layer.info],
                                                                       grayscale)

        style_string += keyframe_string + "  </style>\n"
        
        return head + " <defs>\n" + pattern_string + style_string + " </defs>\n"

    @staticmethod
    def gen_svg_body(context, camera_info):
        """Generates svg body and returns it

        :param context: Context
        :type context: bpy.context
        :param camera_info: Information about the camera used to generate this body
        :type camera_info: CameraInfo
        :return: File body
        :rtype: str
        """
        body = "\n\n\n"
        global STARTTIME
        STARTTIME = datetime.now()
        props = context.scene.export_properties

        ## COLLECTION SORTING

        # If group by collection is not selected, puts all objects into one collection
        if not props.group_by_collections:
            # Converts non-priority annotations into a list of ViewCurve 
            nonprio_anns = []
            if props.curve_convert_annotations:
                nonprio_anns = AnnotationConverter.convert_all_anns(props, 
                                                                    [context.annotation_data], 
                                                                    camera_info, False)

            # Converts all objects as one group                
            collection = camera_info.object_list
            group_name = "scene"
            body += SVGFileGenerator.objects_to_svg_group(props, collection, nonprio_anns, 
                                                          group_name, camera_info)[0]
        else:
            # Creates a list of (name, objects) tuples for every collection
            collections = []

            # Sorts objects into their parent collections
            for obj in camera_info.object_list:
                parent_name = obj.users_collection[0].name
                new_collection = True
                for name, objects in collections:
                    if name == parent_name:
                        objects.append(obj)
                        new_collection = False
                        break
                if new_collection:
                    collections.append((parent_name, [obj,]))
            
            # Converts collections to svg <g> strings and appends them to body
            body += SVGFileGenerator.collections_to_svg_groups(context, collections, camera_info)

        return body
    
    @staticmethod
    def gen_svg_tail(context, camera_info):
        """Generates svg tail and returns it

        :param context: Context
        :type context: bpy.context
        :param camera_info: Information about the camera used to generate this tail
        :type camera_info: CameraInfo
        :return: File tail
        :rtype: str
        """
        tail = ""
        props = context.scene.export_properties

        if props.curve_convert_annotations:
            # Adds priority annotations to the end of the file 
            # (and non priority as well if body is split by collections)
            coord_precision = props.coord_precision
            if props.group_by_collections:
                for el in AnnotationConverter.convert_all_anns(props, [context.annotation_data], 
                                                               camera_info, False):
                    tail += el.to_svg(coord_precision)
            for el in AnnotationConverter.convert_all_anns(props, [context.annotation_data], 
                                                           camera_info, True):
                tail += el.to_svg(coord_precision)

        tail += "\n</svg>"

        return tail

    @staticmethod
    def gen_svg_file(file_name, context, camera_info, append_name):
        """Generates an svg file from a given camera

        :param file_name: Name/path of the output file
        :type file_name: str
        :param context: Context
        :type context: bpy.context
        :param camera_info: Information about the camera used to generate this file
        :type camera_info: CameraInfo
        :param append_name: If True, appends the camera name to the end of the file name
        :type append_name: bool
        :return: (resulting file name, result - 0 if successful 1/2/3/4/5 if error)
        :rtype: (str, int)
        """
        content = ""

        # Creates the final path for this camera
        path = file_name
        if append_name:
            path = file_name[0:-4] + "_" + camera_info.name + ".svg"

        # Opens the file
        try:
            f = open(path, "w", encoding = "utf-8")
        except FileNotFoundError:
            return (path, 1) #display_message("Output directory not found", "Error", "ERROR")
        except PermissionError:
            return (path, 2) #display_message("Permission to open file denied", "Error", "ERROR")
        except OSError:
            return (path, 5)

        # Generates output file content
        content += SVGFileGenerator.gen_svg_head(context, camera_info)
        try:
            content += SVGFileGenerator.gen_svg_body(context, camera_info)
        except ValueError as e:
            traceback.print_exc()
            f.close()
            return (path, 6)
        except RecursionError as e:
            content += "</svg>"
            f.write(content)
            f.close()
            return (path, 3)
        except KeyboardInterrupt as e:
            f.close()
            return (path, 4) #print("Export interrupted")
        
        content += SVGFileGenerator.gen_svg_tail(context, camera_info)

        # Writes and closes output file
        f.write(content)
        f.close()
        return (path, 0)

#
# EXPORT OPERATOR CLASSES
#

class ExportSVGCameraMove(bpy.types.Operator):
    """Moves the first selected camera object to current view"""
    bl_idname = "object.export_move_camera"
    bl_label = "Move Selected Camera To Current View"

    @classmethod
    def poll(cls, context):
        """Polling method
        """
        for obj in context.selected_objects:
            if obj.type == "CAMERA":
                return True
        return False

    def execute(self, context):
        """Execute method of the Move Camera operator

        :param context: Context
        :type context: bpy.context
        :return: Always {"FINISHED"}
        :rtype: Always {"FINISHED"}
        """
        camera_obj = None
        for obj in context.selected_objects:
            if obj.type == "CAMERA":
                camera_obj = obj
                break

        camera_pos = view3d_utils.region_2d_to_origin_3d(context.region,
                                                         context.space_data.region_3d,
                                                         (context.region.width / 2,
                                                          context.region.height / 2))
        #camera_dir = Vector(context.space_data.region_3d.view_location - camera_pos)
        #camera_dir.normalize()
        view_rot = context.space_data.region_3d.view_rotation

        #camera_obj.rotation_quaternion = view_rot
        camera_obj.rotation_euler = view_rot.to_euler()
        camera_obj.location = camera_pos

        return {"FINISHED"}

class ExportSVGOperator(bpy.types.Operator):
    """Exports selected objects"""
    bl_idname = "object.export_svg"
    bl_label = "EXPORT"

    @classmethod
    def poll(cls, context):
        """Polling method
        """
        return context.active_object is not None

    def main_export(self, context):
        """Main method of the export button

        :param context: Context
        :type context: bpy.context
        :return: Always {"FINISHED"}
        :rtype: Always {"FINISHED"}
        """
        global STARTTIME
        STARTTIME = datetime.now()
        props = context.scene.export_properties

        # Gets object list
        object_list = get_object_list(context)

        # Checks if any light source is selected
        valid_light = False
        if props.camera_light or props.selected_point_light is not None:
            valid_light = True
        
        if (EnumPropertyDictionaries.light_source[props.light_type] == 0) and not valid_light:
            display_message(["No light source has been selected"], "Error", "ERROR")
            return {"FINISHED"}

        # Checks .svg extension of the output path
        path = props.output_path
        if path[-4:] != ".svg":
            path += ".svg"

        # Creates a list of all camera_infos from selected cameras
        cameras = []
        if EnumPropertyDictionaries.camera[props.viewport_camera] == 0:
            cameras.append(CameraInfo.view_to_camerainfo(context, object_list))
        else:
            camera_id = 0
            for obj in object_list:
                if obj.type == "CAMERA":
                    cameras.append(CameraInfo.camera_object_to_camerainfo(context, obj, 
                                                                          object_list, camera_id))
                    camera_id += 1

        # Generates svg file for every camera
        if len(cameras) < 1:
            display_message(["No camera has been selected"], "Error", "ERROR")
        elif len(cameras) == 1:
            res_name, res = SVGFileGenerator.gen_svg_file(path, context, cameras[0], False)
            if res == 0:
                display_message(["Selected objects successfully exported to: ", path], 
                                "Success", "INFO")
            else:
                display_message([runtime_error_dict[res]], "Error", "ERROR")
        else:
            success_files = []
            fail_files = []
            for camera in cameras:
                res_name, res = SVGFileGenerator.gen_svg_file(path, context, camera, True)
                if res == 0:
                    success_files.append(res_name)
                elif res == 4:
                    fail_files.append(res_name + "     ERROR: " + runtime_error_dict[res])
                    break
                else:
                    fail_files.append(res_name + "     ERROR: " + runtime_error_dict[res])
            res_msg = [f"Successfully exported {len(success_files)}/{len(cameras)} files:"]
            for name in success_files:
                res_msg.append(f" SUCCESS {name}")
            for name in fail_files:
                res_msg.append(f" FAILED {name}")
            display_message(res_msg, "Success", "INFO")

        """# Copies images if the option is selected
        if props.copy_image_file:
            try:
                copy_images(object_list, path)
            except IOError as e:
                display_message\
                (["Error occured when copying images (files not readable/writeable)"], 
                "Error", "ERROR")"""
    
        return {"FINISHED"}

    def execute(self, context):
        """Execute method of the Export operator

        :param context: Context
        :type context: bpy.context
        :return: Always {"FINISHED"}
        :rtype: Always {"FINISHED"}
        """

        self.main_export(context)
        return {"FINISHED"}

class ExportSVGReset(bpy.types.Operator):
    """Resets options by setting them to their default values (except file path)"""
    bl_idname = "object.export_reset"
    bl_label = "Default settings"

    def execute(self, context):
        """Execute method of the Reset operator

        :param context: Context
        :type context: bpy.context
        :return: Always {"FINISHED"}
        :rtype: Always {"FINISHED"}
        """
        props = context.scene.export_properties

        # Model reset
        props.polygon_override = False
        props.polygon_stroke_width = 0.35
        props.polygon_stroke_same_as_fill = False
        props.polygon_stroke_color = [0.0, 0.0, 0.0, 1.0]
        props.polygon_dashed_stroke = False
        props.polygon_dash_array = [2, 0, 0, 0]
        props.polygon_disable_lighting = False
        props.polygon_use_pattern = False
        props.polygon_custom_pattern = ""
        props.polygon_fill_color = [0.5, 0.5, 0.5, 1.0]
    
        props.backface_culling = False
        props.cut_conflicts = False
        props.cutting_algorithm = "cut.bsp"
        props.polygon_sorting_heuristic = "heuristic.bbmid"
        props.partition_cycles_limit = 500
        
        # Lighting reset
        props.light_type = "light.point"
        props.camera_light = True
        props.light_direction = [-0.303644, 0.259109, 0.916877]
        props.grayscale = False
        props.light_color = [1.0, 1.0, 1.0]
        props.ambient_color = [0.05, 0.05, 0.05]

        # Curve reset
        props.curve_override = False
        props.curve_stroke_width = 1.0
        props.curve_stroke_color = [0.0, 0.0, 0.0, 1.0]
        props.curve_dashed_stroke = False
        props.curve_dash_array = [2, 0, 0, 0]
        props.curve_use_pattern = False
        props.curve_custom_pattern = ""
        props.curve_fill_color = [0.0, 0.0, 0.0, 0.0]
        props.curve_merge_splines = False
        props.curve_fill_evenodd = False
        props.curve_convert_annotations = False
        
        # Text reset
        props.text_override = False
        props.text_stroke_width = 1.0
        props.text_stroke_color = [0.0, 0.0, 0.0, 1.0]
        props.text_dashed_stroke = False
        props.text_dash_array = [2, 0, 0, 0]
        props.text_use_pattern = False
        props.text_custom_pattern = ""
        props.text_fill_color = [0.0, 0.0, 0.0, 0.0]
        props.text_conversion = "text.curve_norot"
        props.text_font_size = 12.0

        """# Image reset
        props.copy_image_file = False"""

        # Camera reset
        props.viewport_camera = "camera.view"
        props.relative_planar_light = False

        # Export reset
        props.selection_method = "sel.sel"
        props.apply_modifiers = "mod.nomod"
        props.global_sorting_option = "sorting.bbmid"
        props.group_by_collections = False
        props.collection_sorting_option = "coll.hier"
        
        props.coord_precision = 1

        display_message(["Settings have been reset to default"], "Success", "INFO")

        return {"FINISHED"}

    def invoke(self, context, event):
        """Invoke method of the Reset operator
        """
        return context.window_manager.invoke_confirm(self, event)

# Based on this tutorial https://sinestesia.co/blog/tutorials/using-uilists-in-blender/
class ExportSVGKeyframeAdd(bpy.types.Operator):
    """Adds a new keyframe to the list of keyframes of the active material"""

    bl_idname = "material.export_keyframe_add"
    bl_label = "Adds a new keyframe"

    def execute(self, context):
        context.material.export_svg_animation_properties.keyframes.add()
        return {"FINISHED"}

class ExportSVGKeyframeDelete(bpy.types.Operator):
    """Deletes a keyframe from the list of keyframes of the active material"""

    bl_idname = "material.export_keyframe_del"
    bl_label = "Deletes a keyframe"

    @classmethod
    def poll(cls, context):
        return context.material.export_svg_animation_properties.keyframes

    def execute(self, context):
        keyframes = context.material.export_svg_animation_properties.keyframes
        index = context.material.export_svg_animation_properties.keyframe_index

        keyframes.remove(index)
        context.material.export_svg_animation_properties.keyframe_index = \
            min(max(0, index - 1), len(keyframes) - 1)

        return {"FINISHED"}

class ExportSVGKeyframeMove(bpy.types.Operator):
    """Moves a keyframe in the list of keyframes of the active material"""

    bl_idname = "material.export_keyframe_move"
    bl_label = "Moves a keyframe in the list"

    direction: bpy.props.EnumProperty(items = (("UP", "Up", ""), ("DOWN", "Down", "")))

    @classmethod
    def poll(cls, context):
        return context.material.export_svg_animation_properties.keyframes

    def move_index(self):
        index = bpy.context.material.export_svg_animation_properties.keyframe_index
        length = len(bpy.context.material.export_svg_animation_properties.keyframes) - 1
        new_index = index + (-1 if self.direction == "UP" else 1)

        bpy.context.material.export_svg_animation_properties.keyframe_index = \
            max(0, min(new_index, length))

    def execute(self, context):
        keyframes = context.material.export_svg_animation_properties.keyframes
        index = context.material.export_svg_animation_properties.keyframe_index

        neighbor = index + (-1 if self.direction == "UP" else 1)
        keyframes.move(neighbor, index)
        self.move_index()

        return {"FINISHED"}

#
# EXPORT PANEL CLASSES
#

class ExportSVGPanel:
    """Parent class of UI panel classes
    """
    bl_category = "Export SVG"
    bl_options = {"DEFAULT_CLOSED"}
    bl_region_type = "UI"
    bl_space_type = "VIEW_3D"

class ExportSVGPanelMain(ExportSVGPanel, bpy.types.Panel):
    """Main panel class
    """
    bl_label = "Export SVG"
    bl_idname = "OBJECT_PT_export_panel"

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context
        """
        layout = self.layout
        layout.label(text = "Export SVG Options Panel")

""" Currently unused
class ExportSVGPanelObj(ExportSVGPanel, bpy.types.Panel):
    Object list panel class
    
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "Selected Objects"
    bl_idname = "OBJECT_PT_export_panel_obj"

    def draw(self, context):
        Draw method of the panel

        :param context: Context
        :type context: bpy.context
        
        layout = self.layout

        # UI Definition

        # row = layout.row()
        # row.label(text = "Selected objects (name):")
        i = 0
        for obj in []:
            if obj.type == "MESH" or obj.type == "CURVE" or obj.type == "FONT" or\
                (obj.type == "EMPTY" and type(obj.data) == bpy.types.Image):
                i += 1
                if i > 4:
                    continue
                row = layout.row()
                row.label(text = "     " + obj.name)
                
        if i == 0:
            row = layout.row()
            row.label(text = "     NO MESH SELECTED")
        elif i > 4:
            row = layout.row()
            row.label(text = "     ... and " + str(i - 4) + " other(s), total " + str(i))
"""
            
class ExportSVGPanelRender(ExportSVGPanel, bpy.types.Panel):
    """Render options panel class
    """
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "MESH Options"
    bl_idname = "OBJECT_PT_export_panel_render"

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context
        """
        layout = self.layout
        props = context.scene.export_properties

        # UI Definition

        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        left_col_align = "RIGHT"
        col_a.alignment = left_col_align

        col_a.label(text="Ignore Materials")
        col_b.prop(props, "polygon_override", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Stroke Width")
        col_b.prop(props, "polygon_stroke_width", text="")

        #if not props.polygon_stroke_same_as_fill:
        sc_lbl = col_a.row()
        sc_lbl.alignment = left_col_align
        sc_lbl.label(text="Stroke Color")
        sc_row = col_b.row()
        sc_row.prop(props, "polygon_stroke_color", text="")

        if not props.polygon_disable_lighting and props.polygon_stroke_same_as_fill:
            sc_lbl.enabled = False
            sc_row.enabled = False

        col_a.label(text="Dashed Stroke")
        ds_row = col_b.row()
        ds_row.prop(props, "polygon_dashed_stroke", text="")

        sda_lbl = col_a.row()
        sda_lbl.alignment = left_col_align
        sda_lbl.label(text="Stroke Dash Array")
        sda_row = col_b.row()
        sda_row.prop(props, "polygon_dash_array", text="")

        if not props.polygon_dashed_stroke:
            sda_lbl.enabled = False
            sda_row.enabled = False

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Pattern Fill")
        cp_row = col_b.row()
        cp_row.prop(props, "polygon_use_pattern", text="")

        if props.polygon_use_pattern:
            col_a.label(text="Pattern String")
            row = col_b.row()
            row.prop(props, "polygon_custom_pattern", text="")
            if check_valid_pattern(props.polygon_custom_pattern):
                row.label(text="", icon="CHECKBOX_HLT")
            else:
                row.label(text="", icon="ERROR")
        else:
            col_a.label(text="Fill Color")
            col_b.prop(props, "polygon_fill_color", text="")

        dl_lbl = col_a.row()
        dl_lbl.alignment = left_col_align
        dl_lbl.label(text="Disable Lighting")
        dl_row = col_b.row()
        dl_row.prop(props, "polygon_disable_lighting", text="")
        if props.polygon_use_pattern:
            dl_lbl.enabled = False
            dl_row.enabled = False

        saf_lbl = col_a.row()
        saf_lbl.alignment = left_col_align
        saf_lbl.label(text="Sync Stroke Color")
        saf_row = col_b.row()
        saf_row.prop(props, "polygon_stroke_same_as_fill", text="")
        if props.polygon_disable_lighting:
            saf_lbl.enabled = False
            saf_row.enabled = False

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Backface Culling")
        col_b.prop(props, "backface_culling", text="")

        col_a.label(text="Cut Conflicting Polygons")
        cc_row = col_b.row()
        cc_row.prop(props, "cut_conflicts", text="")
        if props.cut_conflicts:
            cc_row.label(text="EXPERIMENTAL FEATURE", icon="ERROR")

        ca_lbl = col_a.row()
        ca_lbl.alignment = left_col_align
        ca_lbl.label(text="Cutting Method")
        ca_row = col_b.row()
        ca_row.prop(props, "cutting_algorithm", text="")

        if props.cut_conflicts is False:
            ca_lbl.enabled = False
            ca_row.enabled = False
        else:
            if EnumPropertyDictionaries.cutting[props.cutting_algorithm] != 0:
                col_a.label(text="Depth Sorting")
                col_b.prop(props, "polygon_sorting_heuristic", text="")
            else:
                col_a.label(text="Partition Cycle Limit")
                col_b.prop(props, "partition_cycles_limit", text="")

class ExportSVGPanelLight(ExportSVGPanel, bpy.types.Panel):
    """Lighting options panel class
    """
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "MESH Lighting"
    bl_idname = "OBJECT_PT_export_panel_light"

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context
        """
        layout = self.layout
        props = context.scene.export_properties

        # UI Definition

        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        col_a.alignment = "RIGHT"

        col_a.label(text="Light Type")
        col_b.prop(props, "light_type", text="")

        if EnumPropertyDictionaries.light_source[props.light_type] == 0:
            col_a.label(text="Use PoV As Light Source")
            col_b.prop(props, "camera_light", text="")
            if not props.camera_light:
                col_a.label(text = "Light Source:")
                col_b.prop(props, "selected_point_light", text="")
        else:
            col_a.label(text="")
            col_a.label(text="Light Direction")
            col_a.label(text="")
            col_b.prop(props, "light_direction", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Light Color")
        col_b.prop(props, "light_color", text="")

        col_a.label(text="Ambient Color")
        col_b.prop(props, "ambient_color", text="")

class ExportSVGPanelCurve(ExportSVGPanel, bpy.types.Panel):
    """Curve options panel class
    """
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "CURVE/GPENCIL Options"
    bl_idname = "OBJECT_PT_export_panel_curve"

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context
        """
        layout = self.layout
        props = context.scene.export_properties

        # UI Definition

        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        left_col_align = "RIGHT"
        col_a.alignment = left_col_align

        col_a.label(text="Ignore Materials")
        col_b.prop(props, "curve_override", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Stroke Width")
        col_b.prop(props, "curve_stroke_width", text="")

        col_a.label(text="Stroke Color")
        sc_row = col_b.row()
        sc_row.prop(props, "curve_stroke_color", text="")

        col_a.label(text="Dashed Stroke")
        ds_row = col_b.row()
        ds_row.prop(props, "curve_dashed_stroke", text="")

        sda_lbl = col_a.row()
        sda_lbl.alignment = left_col_align
        sda_lbl.label(text="Stroke Dash Array")
        sda_row = col_b.row()
        sda_row.prop(props, "curve_dash_array", text="")

        if not props.curve_dashed_stroke:
            sda_lbl.enabled = False
            sda_row.enabled = False

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Pattern Fill")
        cp_row = col_b.row()
        cp_row.prop(props, "curve_use_pattern", text="")

        if props.curve_use_pattern:
            col_a.label(text="Pattern String")
            row = col_b.row()
            row.prop(props, "curve_custom_pattern", text="")
            if check_valid_pattern(props.curve_custom_pattern):
                row.label(text="", icon="CHECKBOX_HLT")
            else:
                row.label(text="", icon="ERROR")
        else:
            col_a.label(text="Fill Color")
            col_b.prop(props, "curve_fill_color", text="")

        col_a.label(text="Evenodd Fill Rule")
        col_b.prop(props, "curve_fill_evenodd", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Merge Splines")
        col_b.prop(props, "curve_merge_splines", text="")

        col_a.label(text="Convert Annotations")
        col_b.prop(props, "curve_convert_annotations", text="")

class ExportSVGPanelText(ExportSVGPanel, bpy.types.Panel):
    """Text options panel class
    """
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "FONT Options"
    bl_idname = "OBJECT_PT_export_panel_text"

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context
        """
        layout = self.layout
        props = context.scene.export_properties

        # UI Definition

        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        left_col_align = "RIGHT"
        col_a.alignment = left_col_align

        col_a.label(text="Ignore Materials")
        col_b.prop(props, "text_override", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Stroke Width")
        col_b.prop(props, "text_stroke_width", text="")

        col_a.label(text="Stroke Color")
        sc_row = col_b.row()
        sc_row.prop(props, "text_stroke_color", text="")

        col_a.label(text="Dashed Stroke")
        ds_row = col_b.row()
        ds_row.prop(props, "text_dashed_stroke", text="")

        sda_lbl = col_a.row()
        sda_lbl.alignment = left_col_align
        sda_lbl.label(text="Stroke Dash Array")
        sda_row = col_b.row()
        sda_row.prop(props, "text_dash_array", text="")

        if not props.text_dashed_stroke:
            sda_lbl.enabled = False
            sda_row.enabled = False

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Pattern Fill")
        cp_row = col_b.row()
        cp_row.prop(props, "text_use_pattern", text="")

        if props.text_use_pattern:
            col_a.label(text="Pattern String")
            row = col_b.row()
            row.prop(props, "text_custom_pattern", text="")
            if check_valid_pattern(props.text_custom_pattern):
                row.label(text="", icon="CHECKBOX_HLT")
            else:
                row.label(text="", icon="ERROR")
        else:
            col_a.label(text="Fill Color")
            col_b.prop(props, "text_fill_color", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Text Conversion")
        col_b.prop(props, "text_conversion", text="")

        if EnumPropertyDictionaries.text_options[props.text_conversion] == 0:
            col_a.label(text="Font Size")
            col_b.prop(props, "text_font_size", text="")

""" Currently unused
class ExportSVGPanelImage(ExportSVGPanel, bpy.types.Panel):
    Image options panel class
    
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "Images"
    bl_idname = "OBJECT_PT_export_panel_image"

    def draw(self, context):
        Draw method of the panel

        :param context: Context
        :type context: bpy.context
        
        layout = self.layout
        props = context.scene.export_properties

        # UI Definition

        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        col_a.alignment = "RIGHT"

        col_a.label(text="Create Image Copies")
        col_b.prop(props, "copy_image_file", text="")
"""

class ExportSVGPanelCamera(ExportSVGPanel, bpy.types.Panel):
    """Camera options panel class
    """
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "Cameras"
    bl_idname = "OBJECT_PT_export_panel_camera"

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context
        """
        layout = self.layout
        props = context.scene.export_properties

        # UI Definition

        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        left_col_align = "RIGHT"
        col_a.alignment = left_col_align

        col_a.label(text="Camera Type")
        col_b.prop(props, "viewport_camera", text="")

        if EnumPropertyDictionaries.camera[props.viewport_camera] == 1:
            lbl = col_a.row()
            lbl.alignment = left_col_align
            lbl.label(text="Relative Planar Light")
            row = col_b.row()
            row.prop(props, "relative_planar_light", text="")
            if EnumPropertyDictionaries.light_source[props.light_type] == 0:
                lbl.enabled = False
                row.enabled = False

            col_a.label()
            col_b.label()

            camera_found = False
            multiple_cameras = False
            first_camera = ""
            col_a.label(text = "Cameras In Selection: ")
            for obj in get_object_list(context):
                if obj.type == "CAMERA":
                    if not camera_found:
                        first_camera = obj.name
                        col_b.label(text = obj.name)
                        camera_found = True
                    else:
                        multiple_cameras = True
                        col_a.label()
                        col_b.label(text = obj.name)
            
            if not camera_found:
                col_b.label(text = "NO CAMERA IN SELECTION", icon="ERROR")

            if multiple_cameras:
                col_b.label()
                col_b.label(text = "Multiple SVG files will be generated", icon="ERROR")
            
        row = layout.row()
        row.label()
        row = layout.row()
        row.operator("object.export_move_camera", text=f"Move Selected Camera To Current View", 
                        icon = "OUTLINER_OB_CAMERA")

class ExportSVGPanelExport(ExportSVGPanel, bpy.types.Panel):
    """Export options panel class
    """
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "Export"
    bl_idname = "OBJECT_PT_export_panel_export"

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context
        """
        layout = self.layout
        props = context.scene.export_properties

        # UI Definition

        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        left_col_align = "RIGHT"
        col_a.alignment = left_col_align

        col_a.label(text="Selection Method")
        col_b.prop(props, "selection_method", text="")

        sel_opt = EnumPropertyDictionaries.selection[props.selection_method]
        if sel_opt == 1 or sel_opt == 2:
            col_a.label(text="Collection")
            col_b.prop(props, "selected_collection", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Data Evaluation")
        col_b.prop(props, "apply_modifiers", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Depth Sorting")
        col_b.prop(props, "global_sorting_option", text="")

        col_a.label(text="Group By Collections")
        col_b.prop(props, "group_by_collections", text="")

        cds_lbl = col_a.row()
        cds_lbl.alignment = left_col_align
        cds_lbl.label(text="Collection Depth Sorting")
        cds_row = col_b.row()
        cds_row.prop(props, "collection_sorting_option", text="")

        if not props.group_by_collections:
            cds_lbl.enabled = False
            cds_row.enabled = False

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Grayscale")
        col_b.prop(props, "grayscale", text="")

        col_a.label(text="Coordinates Precision")
        col_b.prop(props, "coord_precision", text="")

        row = layout.row()
        row = layout.row()
        row = layout.row()
        row.label(text = "Output File Path:")
        row = layout.row()
        row.prop(props, "output_path", text = "")
        row = layout.row()
        row.scale_y = 2
        row.operator("object.export_svg", text="EXPORT", icon = "OUTPUT")
        row = layout.row()
        row.operator("object.export_reset", text="Default Settings", icon = "FILE_REFRESH")

class ExportSVGMaterialPanel(bpy.types.Panel):
    """Creates a Panel in the Material properties window for displaying SVG material properties
    """

    bl_label = "Export SVG Properties"
    bl_idname = "MATERIAL_PT_export_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"

    def draw_global_mesh(self, context):
        """Draws global mesh settings into the material panel
        
        :param context: Context
        :type context: bpy.context
        """

        layout = self.layout
        mat = None
        obj = context.object

        props = context.scene.export_properties

        # UI Definition

        row = layout.row()
        row.label(text="No material has been assigned to this mesh/face/slot.", icon="ERROR")
        row = layout.row()
        row.label(text="The Global Model options will be used for conversion instead:")

        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        col_a.alignment = "RIGHT"

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Stroke Width")
        col_b.prop(props, "polygon_stroke_width", text="")

        #if not props.polygon_stroke_same_as_fill:
        col_a.label(text="Stroke Color")
        sc_row = col_b.row()
        sc_row.prop(props, "polygon_stroke_color", text="")

        col_a.label(text="Dashed Stroke")
        ds_row = col_b.row()
        ds_row.prop(props, "polygon_dashed_stroke", text="")

        col_a.label(text="Stroke Dash Array")
        sda_row = col_b.row()
        sda_row.prop(props, "polygon_dash_array", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Pattern Fill")
        cp_row = col_b.row()
        cp_row.prop(props, "polygon_use_pattern", text="")

        if props.polygon_use_pattern:
            col_a.label(text="Custom Pattern")
            row = col_b.row()
            row.prop(props, "polygon_custom_pattern", text="")
            if check_valid_pattern(props.polygon_custom_pattern):
                row.label(text="", icon="CHECKBOX_HLT")
            else:
                row.label(text="", icon="ERROR")
        else:
            col_a.label(text="Fill Color")
            col_b.prop(props, "polygon_fill_color", text="")

        col_a.label(text="Ignore Lighting")
        dl_row = col_b.row()
        dl_row.prop(props, "polygon_disable_lighting", text="")

        col_a.label(text="Use Lighted Fill Color As Stroke Color")
        saf_row = col_b.row()
        saf_row.prop(props, "polygon_stroke_same_as_fill", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Backface Culling")
        col_b.prop(props, "backface_culling", text="")

        col_a.label(text="Cut Conflicting Polygons")
        col_b.prop(props, "cut_conflicts", text="")

        col_a.label(text="Cutting Method")
        ca_row = col_b.row()
        ca_row.prop(props, "cutting_algorithm", text="")

        if props.cut_conflicts is False:
            ca_row.enabled = False
        else:
            if not props.cutting_algorithm == "cut.bsp":
                col_a.label(text="Polygon Depth Sorting Method")
                col_b.prop(props, "polygon_sorting_heuristic", text="")
            else:
                col_a.label(text="Partition Cycle Limit")
                col_b.prop(props, "partition_cycles_limit", text="")

        col_a.enabled = False
        col_b.enabled = False

    def draw_global_curve(self, context):
        """Draws global curve settings into the material panel
        
        :param context: Context
        :type context: bpy.context
        """

        layout = self.layout
        mat = None
        obj = context.object

        props = context.scene.export_properties

        # UI Definition

        row = layout.row()
        row.label(text="No material has been assigned to this curve/spline/slot.", icon="ERROR")
        row = layout.row()
        row.label(text="The Global Curve options will be used for conversion instead:")

        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        col_a.alignment = "RIGHT"

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Stroke Width")
        col_b.prop(props, "curve_stroke_width", text="")

        col_a.label(text="Stroke Color")
        sc_row = col_b.row()
        sc_row.prop(props, "curve_stroke_color", text="")

        col_a.label(text="Dashed Stroke")
        ds_row = col_b.row()
        ds_row.prop(props, "curve_dashed_stroke", text="")

        col_a.label(text="Stroke Dash Array")
        sda_row = col_b.row()
        sda_row.prop(props, "curve_dash_array", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Pattern Fill")
        cp_row = col_b.row()
        cp_row.prop(props, "curve_use_pattern", text="")

        if props.curve_use_pattern:
            col_a.label(text="Custom Pattern")
            row = col_b.row()
            row.prop(props, "curve_custom_pattern", text="")
            if check_valid_pattern(props.curve_custom_pattern):
                row.label(text="", icon="CHECKBOX_HLT")
            else:
                row.label(text="", icon="ERROR")
        else:
            col_a.label(text="Fill Color")
            col_b.prop(props, "curve_fill_color", text="")

        col_a.label(text="Evenodd Fill Rule")
        col_b.prop(props, "curve_fill_evenodd", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Merge Splines")
        col_b.prop(props, "curve_merge_splines", text="")

        col_a.enabled = False
        col_b.enabled = False

    def draw_global_text(self, context):
        """Draws global text settings into the material panel
        
        :param context: Context
        :type context: bpy.context
        """

        layout = self.layout
        mat = None
        obj = context.object

        props = context.scene.export_properties

        # UI Definition

        row = layout.row()
        row.label(text="No material has been assigned to this text/slot.", icon="ERROR")
        row = layout.row()
        row.label(text="The Global Text options will be used for conversion instead:")

        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        col_a.alignment = "RIGHT"

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Stroke Width")
        col_b.prop(props, "text_stroke_width", text="")

        col_a.label(text="Stroke Color")
        sc_row = col_b.row()
        sc_row.prop(props, "text_stroke_color", text="")

        col_a.label(text="Dashed Stroke")
        ds_row = col_b.row()
        ds_row.prop(props, "text_dashed_stroke", text="")

        col_a.label(text="Stroke Dash Array")
        sda_row = col_b.row()
        sda_row.prop(props, "text_dash_array", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Pattern Fill")
        cp_row = col_b.row()
        cp_row.prop(props, "text_use_pattern", text="")

        if props.text_use_pattern:
            col_a.label(text="Custom Pattern")
            row = col_b.row()
            row.prop(props, "text_custom_pattern", text="")
            if check_valid_pattern(props.text_custom_pattern):
                row.label(text="", icon="CHECKBOX_HLT")
            else:
                row.label(text="", icon="ERROR")
        else:
            col_a.label(text="Fill Color")
            col_b.prop(props, "text_fill_color", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Text Conversion")
        col_b.prop(props, "text_conversion", text="")

        if EnumPropertyDictionaries.text_options[props.text_conversion] == 0:
            col_a.label(text="Font Size")
            col_b.prop(props, "text_font_size", text="")

        col_a.enabled = False
        col_b.enabled = False

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context"""

        layout = self.layout
        mat = context.material
        obj = context.object

        # UI Definition

        if obj is None:
            row = layout.row()
            row.label(text="NO OBJECT SELECTED, cannot display Export SVG properties")

        if (obj.type != "MESH") and (obj.type != "CURVE") and (obj.type != "FONT") and \
           (obj.type != "GPENCIL"):
            row = layout.row()
            row.label(text="Invalid selected object type: " + obj.type)
            row = layout.row()
            row.label(text="Select object of type MESH, CURVE, GPENCIL"\
                      " or FONT to edit its individual SVG material properties")
            return

        valid_material = True
        if mat is None:
            valid_material = False

        svg_type = ""
        if obj.type == "MESH":
            if not valid_material:
                self.draw_global_mesh(context)
                return
            svg_type = "<polygon>"
        elif obj.type == "CURVE" or obj.type == "GPENCIL":
            if not valid_material:
                self.draw_global_curve(context)
                return
            svg_type = "<path>"
        elif obj.type == "FONT":
            if not valid_material:
                self.draw_global_text(context)
                return
            props = mat.export_svg_properties
            text_opt = EnumPropertyDictionaries.text_options[props.text_conversion]
            if text_opt == 0:
                svg_type = "<text>"
            elif text_opt == 1 or text_opt == 2:
                svg_type = "<path>"
            else:
                svg_type = "<polygon>"

        global_props = context.scene.export_properties
        disabled_types = []
        if global_props.polygon_override:
            disabled_types.append("MESH")
        if global_props.curve_override:
            disabled_types.append("CURVE")
            disabled_types.append("GPENCIL")
        if global_props.text_override:
            disabled_types.append("FONT")
        if disabled_types != []:
            row = layout.row()
            row.label(text="The following types are set to ignore materials:", icon="ERROR")
            s = "           "
            for t in disabled_types:
                s += t + "    "
            row = layout.row()
            row.label(text=s)
        

        props = mat.export_svg_properties
        
        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        left_col_align = "RIGHT"
        col_a.alignment = left_col_align

        """col_a.label(text="Material Name")
        #col_b.label(text=mat.name)
        row = col_b.row()
        row.label(text=mat.name)
        if not check_valid_css_name(mat.name):
            row.label(text="Will be renamed", icon="ERROR")
        row.enabled = False
        col_a.label(text="Object Name")
        #col_b.label(text=obj.name)
        row = col_b.row()
        row.label(text=obj.name)
        row.enabled = False
        col_a.label(text="Blender Object Type")
        #col_b.label(text=obj.type)
        row = col_b.row()
        row.label(text=obj.type)
        row.enabled = False
        col_a.label(text="SVG Type")
        #col_b.label(text=svg_type)
        row = col_b.row()
        row.label(text=svg_type)
        row.enabled = False

        col_a.label(text="")
        col_b.label(text="")
        """

        col_a.label(text="Stroke Width")
        col_b.prop(props, "stroke_width", text="")
        
        col_a.label(text="Stroke Color")
        sc_row = col_b.row()
        sc_row.prop(props, "stroke_color", text="")
        col_a.label(text="Dashed Stroke")
        ds_row = col_b.row()
        ds_row.prop(props, "dashed_stroke", text="")
        sda_row = None
        if props.dashed_stroke:
            col_a.label(text="Stroke Dash Array")
            sda_row = col_b.row()
            sda_row.prop(props, "stroke_dash_array", text="")

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Pattern Fill")
        col_b.prop(props, "use_pattern", text="")
        if props.use_pattern:
            col_a.label(text="Pattern String")
            row = col_b.row()
            row.prop(props, "custom_pattern", text="")
            if check_valid_pattern(props.custom_pattern):
                row.label(text="", icon="CHECKBOX_HLT")
            else:
                row.label(text="", icon="ERROR")
        else:
            col_a.label(text="Fill Color")
            col_b.prop(props, "fill_color", text="")

        col_a.label(text="")
        col_b.label(text="")
        
        lbl = col_a.row()
        lbl.alignment = left_col_align
        lbl.label(text="(MESH) Disable Lighting")
        row = col_b.row()
        row.prop(props, "ignore_lighting", text="")
        if obj.type != "MESH" or props.use_pattern:
            lbl.enabled = False
            row.enabled = False

        lbl = col_a.row()
        lbl.alignment = left_col_align
        lbl.label(text="(MESH) Sync Stroke Color")
        row = col_b.row()
        row.prop(props, "stroke_equals_fill", text="")
        if obj.type != "MESH" or props.ignore_lighting:
            lbl.enabled = False
            row.enabled = False

        col_a.label(text="")
        col_b.label(text="")

        lbl1 = col_a.row()
        lbl1.alignment = left_col_align
        lbl1.label(text="(CURVE) Evenodd Fill Rule")
        row1 = col_b.row()
        row1.prop(props, "fill_evenodd", text="")
        lbl2 = col_a.row()
        lbl2.alignment = left_col_align
        lbl2.label(text="(CURVE) Merge Splines")
        row2 = col_b.row()
        row2.prop(props, "merge_splines", text="")
        if obj.type != "CURVE":
            lbl1.enabled = False
            lbl2.enabled = False
            row1.enabled = False
            row2.enabled = False

        col_a.label(text="")
        col_b.label(text="")

        lbl = col_a.row()
        lbl.alignment = left_col_align
        lbl.label(text="(FONT) Text Conversion")
        row = col_b.row()
        row.prop(props, "text_conversion", text="")
        if obj.type != "FONT":
            lbl.enabled = False
            row.enabled = False
        else:
            if EnumPropertyDictionaries.text_options[props.text_conversion] == 0:
                col_a.label(text="Font Size")
                col_b.prop(props, "text_font_size", text="")

# Based on this tutorial https://sinestesia.co/blog/tutorials/using-uilists-in-blender/
class ExportSVGKeyframeList(bpy.types.UIList):
    """UI list containing all keyframes
    """

    def draw_item(self, context, layout, data, item, icon, active_data, acitve_propname, index):
        """Draw method of the UI list
        """
        custom_icon = "SEQUENCE"
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            layout.label(text = item.name, icon = custom_icon)
        elif self.layout_type in {"GRID"}:
            layout.alignment = "CENTER"
            layout.label(text = "", icon = custom_icon)

class ExportSVGAnimationPanel(bpy.types.Panel):
    """Creates a Panel in the Material properties window for displaying SVG animation properties
    """

    bl_label = "Export SVG CSS Animation"
    bl_idname = "MATERIAL_PT_export_animation_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"


    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context"""

        layout = self.layout
        mat = context.material
        obj = context.object

        # UI Definition

        if obj is None:
            row = layout.row()
            row.label(text="NO OBJECT SELECTED, cannot display Export SVG animation properties")
            return

        if mat is None:
            row = layout.row()
            row.label(text="No material has been assigned to this object/slot")
            return

        mat_props = mat.export_svg_properties
        props = mat.export_svg_animation_properties
        
        split = layout.split(factor=0.4, align=True)
        col_a = split.column()
        col_b = split.column()

        left_col_align = "RIGHT"
        col_a.alignment = left_col_align

        
        col_a.label(text="Enable CSS Animations")
        col_b.prop(mat_props, "enable_animations", text="")
        if not mat_props.enable_animations:
            return

        col_a.label(text="Linked To")
        col_b.prop(props, "linked_material", text="")

        if props.linked_material is not None:
            lbl = layout.label(text=f"Animation properties will be copied from material"\
                               f" \"{props.linked_material.name}\".")
            return

        col_a.label(text="")
        col_b.label(text="")

        col_a.label(text="Cycle Duration (s)")
        col_b.prop(props, "duration", text="")

        col_a.label(text="Delay (s)")
        col_b.prop(props, "delay", text="")

        col_a.label(text="Cycle Count")
        row = col_b.row()
        row.prop(props, "infinite", text="Infinite")
        if not props.infinite:
            row.prop(props, "iteration_count", text="")

        lbl = col_a.row()
        row = col_b.row()
        lbl.alignment = left_col_align
        lbl.label(text="Fill Mode")
        row.prop(props, "fill_mode", text="")
        if props.infinite:
            lbl.enabled = False
            row.enabled = False

        col_a.label(text="Direction")
        col_b.prop(props, "direction", text="")

    
        col_a.label(text="Timing Function")
        col_b.prop(props, "timing_function", text="")

        col_a.label(text="")
        col_b.label(text="")

        row = layout.row()
        row.label(text="Keyframe List:")

        row = layout.row()
        row.template_list("ExportSVGKeyframeList", "KeyframeList", 
                          props, "keyframes", props, "keyframe_index")

        row = layout.row()
        row.operator("material.export_keyframe_add", text="New Keyframe")
        row.operator("material.export_keyframe_del", text="Remove Keyframe")
        row.operator("material.export_keyframe_move", text="Move Up").direction = "UP"
        row.operator("material.export_keyframe_move", text="Move Down").direction = "DOWN"

        if props.keyframe_index >= 0 and props.keyframes:
            keyframe = props.keyframes[props.keyframe_index]

            split = layout.split(factor=0.4, align=True)
            col_a = split.column()
            col_b = split.column()

            left_col_align = "RIGHT"
            col_a.alignment = left_col_align


            col_a.label(text="Name")
            col_b.prop(keyframe, "name", text="")

            col_a.label(text="Percentage")
            col_b.prop(keyframe, "percentage", text="")


            col_a.label(text="")
            col_b.label(text="")

            subsplit = col_a.split(factor=0.4, align=True)
            col_a1 = subsplit.column()
            col_a2 = subsplit.column()

            #col_a1.alignment = "CENTER"
            col_a2.alignment = "RIGHT"

            
            col_a1.prop(keyframe, "a_stroke_width", text="")
            lbl = col_a2.row()
            lbl.label(text="Stroke Width")
            prp = col_b.row()
            prp.prop(keyframe, "stroke_width", text="")
            if not keyframe.a_stroke_width:
                lbl.enabled = False
                prp.enabled = False

            col_a1.prop(keyframe, "a_stroke_color", text="")
            lbl = col_a2.row()
            lbl.label(text="Stroke Color")
            prp = col_b.row()
            prp.prop(keyframe, "stroke_color", text="")
            if not keyframe.a_stroke_color:
                lbl.enabled = False
                prp.enabled = False

            col_a1.prop(keyframe, "a_dashed_stroke", text="")
            lbl = col_a2.row()
            lbl.label(text="Dashed Stroke")
            prp = col_b.row()
            prp.prop(keyframe, "stroke_dash_array", text="")
            if not keyframe.a_dashed_stroke:
                lbl.enabled = False
                prp.enabled = False

            col_a1.prop(keyframe, "a_fill_color", text="")
            lbl = col_a2.row()
            lbl.label(text="Fill Color")
            prp = col_b.row()
            prp.prop(keyframe, "fill_color", text="")
            if not keyframe.a_fill_color:
                lbl.enabled = False
                prp.enabled = False

            col_a.label(text="")
            col_b.label(text="")

            col_a.label(text="")
            col_b.label(text="")

            col_a.label(text="(EXPERIMENTAL) Transformations")
            col_b.prop(keyframe, "transform", text="")

            if keyframe.transform:

                col_a.label(text="")
                col_b.label(text="")

                col_a.label(text=f"Translate ({keyframe.translate_units})")
                row = col_b.row()
                row.prop(keyframe, "translate", text="")
                row.prop(keyframe, "translate_units", text="")

                col_a.label(text="")
                col_b.label(text="")

                col_a.label(text="Scale")
                row = col_b.row()
                row.prop(keyframe, "scale", text="")

                col_a.label(text="")
                col_b.label(text="")

                col_a.label(text="Skew (deg)")
                row = col_b.row()
                row.prop(keyframe, "skew", text="")

                col_a.label(text="")
                col_b.label(text="")

                col_a.label(text="Rotation Axis ")
                row = col_b.row()
                row.prop(keyframe, "rotate3d", text="")

                col_a.label(text="Rotation Angle (deg)")
                col_b.prop(keyframe, "rotate_angle", text="")

                

                col_a.label(text="")
                col_b.label(text="")

                col_a.label(text="Transform Origin")
                col_b.prop(keyframe, "transform_origin", text="")
            
#
# (UN)REGISTER FUNCTIONS
#

def register():
    """ Function for registering classes
    """
    bpy.utils.register_class(ExportSVGProperties)
    bpy.utils.register_class(ExportSVGMaterialProperties)
    bpy.utils.register_class(ExportSVGKeyframeProperties)
    bpy.utils.register_class(ExportSVGAnimationProperties)
    bpy.types.Scene.export_properties = \
        bpy.props.PointerProperty(type = ExportSVGProperties)
    bpy.types.Material.export_svg_properties = \
        bpy.props.PointerProperty(type = ExportSVGMaterialProperties)
    bpy.types.Material.export_svg_animation_properties = \
        bpy.props.PointerProperty(type = ExportSVGAnimationProperties)

    bpy.utils.register_class(ExportSVGCameraMove)
    bpy.utils.register_class(ExportSVGOperator)
    bpy.utils.register_class(ExportSVGReset)
    bpy.utils.register_class(ExportSVGKeyframeAdd)
    bpy.utils.register_class(ExportSVGKeyframeDelete)
    bpy.utils.register_class(ExportSVGKeyframeMove)

    bpy.utils.register_class(ExportSVGPanelMain)
    #bpy.utils.register_class(ExportSVGPanelObj)
    bpy.utils.register_class(ExportSVGPanelRender)
    bpy.utils.register_class(ExportSVGPanelLight)
    bpy.utils.register_class(ExportSVGPanelCurve)
    bpy.utils.register_class(ExportSVGPanelText)
    #bpy.utils.register_class(ExportSVGPanelImage)
    bpy.utils.register_class(ExportSVGPanelCamera)
    bpy.utils.register_class(ExportSVGPanelExport)

    bpy.utils.register_class(ExportSVGMaterialPanel)
    bpy.utils.register_class(ExportSVGKeyframeList)
    bpy.utils.register_class(ExportSVGAnimationPanel)



def unregister():
    """Function for unregistering classes
    """
    bpy.utils.unregister_class(ExportSVGProperties)
    bpy.utils.unregister_class(ExportSVGMaterialProperties)
    bpy.utils.unregister_class(ExportSVGKeyframeProperties)
    bpy.utils.unregister_class(ExportSVGAnimationProperties)
    del bpy.types.Scene.export_properties
    del bpy.types.Material.export_svg_properties
    del bpy.types.Material.export_svg_animation_properties

    bpy.utils.unregister_class(ExportSVGCameraMove)
    bpy.utils.unregister_class(ExportSVGOperator)
    bpy.utils.unregister_class(ExportSVGReset)
    bpy.utils.unregister_class(ExportSVGKeyframeAdd)
    bpy.utils.unregister_class(ExportSVGKeyframeDelete)
    bpy.utils.unregister_class(ExportSVGKeyframeMove)


    bpy.utils.unregister_class(ExportSVGPanelMain)
    #bpy.utils.unregister_class(ExportSVGPanelObj)
    bpy.utils.unregister_class(ExportSVGPanelRender)
    bpy.utils.unregister_class(ExportSVGPanelLight)
    bpy.utils.unregister_class(ExportSVGPanelCurve)
    bpy.utils.unregister_class(ExportSVGPanelText)
    #bpy.utils.unregister_class(ExportSVGPanelImage)
    bpy.utils.unregister_class(ExportSVGPanelCamera)
    bpy.utils.unregister_class(ExportSVGPanelExport)

    bpy.utils.unregister_class(ExportSVGMaterialPanel)
    bpy.utils.unregister_class(ExportSVGKeyframeList)
    bpy.utils.unregister_class(ExportSVGAnimationPanel)

#
# MAIN
#

if __name__ == "__main__":
    register()
