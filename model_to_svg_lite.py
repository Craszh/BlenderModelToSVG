""" Blender addon for converting and exporting a 3D model to an SVG file """

# Metadata
__author__ = "Jiří Kopáček"
__license__ = "GNU GPL v3.0"
__version__ = "1.0"
__date__ = "20. 04. 2021"

# Blender addon metadata
bl_info = {
    "name" : "Model to SVG export LITE",
    "description" : "Converts a 3D model to vector graphics and exports it as an SVG file",
    "author" : "Jiří Kopáček",
    "version" : (0, 9),
    "blender" : (2,90,0),
    "location" : "View3D > Sidebar > Export SVG",
    "warning" : "Lite version contains only 1 cutting method (check documentation)",
    "url": "https://github.com/Craszh/BlenderModelToSVG",
    "wiki_url": "https://github.com/Craszh/BlenderModelToSVG",
    "category" : "Import-Export",
}

# Imports
from copy import deepcopy
from datetime import datetime
import numpy
import bpy
import bmesh
import math
from mathutils.geometry import distance_point_to_plane
from mathutils.geometry import intersect_line_plane
from mathutils.geometry import normal as get_normal
from mathutils import Vector
from mathutils import Matrix
from bpy_extras import view3d_utils
import traceback

#
# Global settings
#

VERT_DECIMALS = 5
PLANE_DISTANCE_THRESHOLD = 0.001
POLYGON_CULL_THRESHOLD = 1E-6
POLYGON_CUT_PRECISION = 1000.0
STARTTIME = datetime.now()

#
# Misc methods
#

def display_message(message_text, message_title, message_icon):
    """Method for displaying a message to the user on screen

    :param message_text: Text body of the message
    :type message_text: string
    :param message_title: Title of the message
    :type message_title: string
    :param message_icon: Icon of the message
    :type message_icon: string
    """
    def draw(self, context):
        self.layout.label(text = message_text)

    bpy.context.window_manager.popup_menu(draw, title = message_title, icon = message_icon)

#
# PROPERTIES
#

class ExportSVGProperties(bpy.types.PropertyGroup):
    """Class storing the properties of the Export SVG plugin
    """

    cutting_options = [
        ("cut.bsp", "BSP Tree",
         "Partitions and sorts the scene using a BSP tree", "", 0),
    ]

    sorting_options = [
        ("heuristic.bbmin", "Closest vertex",
         "Sorts polygons based on the depth of their closest vertex", "", 0),
        ("heuristic.bbmid", "Center",
         "Sorts polygons based on the depth of their center", "", 1),
        ("heuristic.bbmax", "Furthest vertex",
         "Sorts polygons based on the depth of their furthest vertex", "", 2),
        ("heuristic.weightmid", "Weighted center",
         "Sorts polygons based on the average depth of all vertices", "", 3)
    ]

    # Stores the output filepath
    output_path: bpy.props.StringProperty(
        name = "Output path",
        description = "Defines the path to the outputted file (.svg will be appended if missing)",
        default = "C:\\tmp\\output.svg",
        maxlen = 255,
        subtype = "FILE_PATH"
    )

    # Stores the custom stroke option
    custom_strokes: bpy.props.BoolProperty(
        name = "Override default stroke color",
        description = "Allows override of the color of polygon strokes, " + \
                      "otherwise default color of strokes is the same as the polygon fill color",
        default = False
    )

    # Stores the stroke color option
    stroke_color: bpy.props.FloatVectorProperty(
        name = "Stroke color",
        description = "Custom color of polygon strokes",
        min = 0.0,
        max = 1.0,
        default = [0.0, 0.0, 0.0, 1.0],
        size = 4,
        subtype = "COLOR"
    )

    # Stores the custom fill option
    custom_fill: bpy.props.BoolProperty(
        name = "Override default polygon color",
        description = "Allows override of the fill color of polygons, " + \
                      "otherwise default color is calculated based on lighting options. " + \
                      "It is recommended to override default strokes when overriding fill color",
        default = False
    )

    # Stores the fill color option
    fill_color: bpy.props.FloatVectorProperty(
        name = "Polygon color",
        description = "Custom fill color of polygons",
        min = 0.0,
        max = 1.0,
        default = [0.5, 0.5, 0.5, 1.0],
        size = 4,
        subtype = "COLOR"
    )

    # Stores the cutting algorithm option
    cutting_algorithm: bpy.props.EnumProperty(
        items = cutting_options,
        description = "Defines what algorithm is used for dealing with conflicting polygons",
        default = "cut.bsp",
        name = "Cutting"
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

    # Stores the sorting heuristic option
    sorting_heuristic: bpy.props.EnumProperty(
        items = sorting_options,
        description = "Defines what rule is used for sorting the final list of polygons",
        default = "heuristic.bbmid",
        name = "Sorting"
    )

    # Stores the quick depth sort option
    cut_conflicts: bpy.props.BoolProperty(
        name = "Cut conflicting faces",
        description = "Slower exporting and larger file size, " + \
            "however intersecting and overlapping polygons are displayed more precisely",
    )

    # Stores the backface culling option
    backface_culling: bpy.props.BoolProperty(
        name = "Backface culling",
        description = "Ignores polygons that are not facing the camera"
    )

    # Stores the grayscale option
    grayscale: bpy.props.BoolProperty(
        name = "Grayscale",
        description = "Ignores colors and calculates only the gray value " + \
            "based on the rotation of the polygon and position of the light source",
    )

    # Stores the ignore material option
    ignore_materials: bpy.props.BoolProperty(
        name = "Ignore materials",
        description = "Ignores materials of individual faces, " + \
            "resulting color is calculated as if the material is white and opaque",
    )

    # Stores the minimum brightness value
    min_brightness: bpy.props.IntProperty(
        name = "Min",
        description = "Minimum brightness value of the darkest polygons",
        default = 0,
        min = 0,
        max = 255,
        soft_min = 0,
        soft_max = 255
    )

    # Stores the maximum brightness value
    max_brightness: bpy.props.IntProperty(
        name = "Max",
        description = "Maximum brightness value of the brightest polygons",
        default = 255,
        min = 0,
        max = 255,
        soft_min = 0,
        soft_max = 255
    )

    # Stores the camera light option
    camera_light: bpy.props.BoolProperty(
        name = "Use point of view as light source",
        description = "Current point of view is the main light source instead of a light object",
        default = True
    )

    # Stores the point light option
    point_light: bpy.props.BoolProperty(
        name = "Use point light",
        description = "Changes the type of light source from planar to point",
    )

    # Stores the planar light direction
    light_direction: bpy.props.FloatVectorProperty(
        name = "",
        description = "Specifies the angle under which light reaches the surface of the object",
        default = [-0.303644, 0.259109, 0.916877],
        subtype = "DIRECTION",
    )

    # World light direction (hidden from user)
    world_light_dir: bpy.props.FloatVectorProperty(
        name = "Planar light direction in world coordinates",
        description = "Direction from the source of the planar light to the scene",
    )

    # Stores the light color values
    light_color: bpy.props.FloatVectorProperty(
        name = "Light color",
        description = "Color of the light emitted by the light source",
        min = 0.0,
        max = 1.0,
        default = [1.0, 1.0, 1.0],
        subtype = "COLOR"
    )

    # Stores the ambient light color values
    ambient_color: bpy.props.FloatVectorProperty(
        name = "Ambient color",
        description = "Color of the ambient light in the scene",
        min = 0.0,
        max = 1.0,
        default = [0.05, 0.05, 0.05],
        subtype = "COLOR"
    )

    # Stores the stroke width value
    stroke_width: bpy.props.FloatProperty(
        name = "Stroke width",
        description = "Stroke width of polygons in the svg file, thinner strokes might make " + \
            "polygons look disjointed, thicker strokes might create artifacts on smaller polygons",
        default = 0.35,
        min = 0.0,
        max = 3.0,
        soft_min = 0.0,
        soft_max = 3.0
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
# VIEWPOLYGON TYPE
#

class ViewPolygon:
    """Class representing a polygon in viewport
    """

    def __init__(self, verts, depth, rgb_color, opacity, set_bounds=False):
        """Constructor method

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
        """
        # vert = (x, y, z)
        self.verts = verts
        self.depth = depth
        # rgb = (r, g, b)
        self.rgb_color = rgb_color
        self.stroke_color = rgb_color
        self.opacity = opacity
        self.stroke_opacity = opacity
        self.normal = get_normal(verts)
        # Newell marked
        self.marked = False
        # Bounding box [xMin, xMax, yMin, yMax, zMin, zMax]
        self.bounds = None
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

    @staticmethod
    def recalculate_bounds(view_polygon):
        """Recalculates the bounds of the polygon

        :param view_polygon: Polygon to recalculates
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

#
# CLIPPING
#

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
    def clip_2d_polygon(context, verts_2d):
        """Returns polygon if polygon is inside viewport,
           returns None if outside viewport, returns clipped polygon if both

        :param context: Context
        :type context: bpy.context
        :param verts_2d: Unclipped viewport polygon
        :type verts_2d: List of float[3]
        :return: Viewport polygon with all vertices inside the screen boundary or None
        :rtype: List of float[3] or None
        """
        res_x = context.region.width
        res_y = context.region.height

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
# MESH CONVERSION
#

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
    def get_face_color(context, face, face_normal, face_material, light_pos):
        """Calculates color of the face based on options and parameters

        :param context: Context
        :type context: bpy.context
        :param face: Face of the mesh
        :type face: BMFace
        :param face_normal: Normal of the face in world coordinates (NOT LOCAL COORDINATES)
        :type face_normal: float[3]
        :param face_material: Material of the face
        :type face_material: bpy.types.Material
        :param light_pos: Position of the light source in world coordinates
        :type light_pos: float[3]
        :return: Final color as (r, g, b, opacity), rgb as (0-255), opacity as (0.0-1.0)
        :rtype: float[4]
        """

        # If custom fill color is selected, overrides lighting
        if context.scene.export_properties.custom_fill:
            return (int(context.scene.export_properties.fill_color[0] * 255),
                    int(context.scene.export_properties.fill_color[1] * 255),
                    int(context.scene.export_properties.fill_color[2] * 255),
                    context.scene.export_properties.fill_color[3])

        # Gets the angle between direction to the light and face normal
        dir_vec = Vector(context.scene.export_properties.world_light_dir)
        if context.scene.export_properties.point_light:
            dir_vec = light_pos - face.verts[0].co

        cosine = ((dir_vec @ face_normal) /
                  (numpy.linalg.norm(dir_vec)) * numpy.linalg.norm(face_normal))

        # Calculates only gray if grayscale option
        if context.scene.export_properties.grayscale:
            min_val = context.scene.export_properties.min_brightness
            max_val = context.scene.export_properties.max_brightness
            opacity = 1.0
            if context.scene.export_properties.ignore_materials or face_material is not None:
                opacity = face_material.diffuse_color[3]
            brightness = round(numpy.clip(min_val,
                                          max(cosine, 0) * (max_val - min_val) + min_val,
                                          max_val))
            return (brightness,
                    brightness,
                    brightness,
                    opacity)

        light_color = context.scene.export_properties.light_color
        light_ambient = context.scene.export_properties.ambient_color

        # Calculates a default shadow if the face does not have a material assigned
        if context.scene.export_properties.ignore_materials or face_material is None:
            brightness = max(cosine, 0)

            #print(brightness, light_color[0], light_ambient[0] + brightness * light_color[0])
            return (round(min(((light_ambient[0] + brightness * light_color[0]) * 255), 255)),
                    round(min(((light_ambient[1] + brightness * light_color[1]) * 255), 255)),
                    round(min(((light_ambient[2] + brightness * light_color[2]) * 255), 255)),
                    1.0)
        else:
            brightness = max(cosine, 0)
            return (round(min(((face_material.diffuse_color[0] * light_ambient[0] + face_material.diffuse_color[0] * brightness * light_color[0]) * 255), 255)),
                    round(min(((face_material.diffuse_color[1] * light_ambient[1] + face_material.diffuse_color[1] * brightness * light_color[1]) * 255), 255)),
                    round(min(((face_material.diffuse_color[2] * light_ambient[2] + face_material.diffuse_color[2] * brightness * light_color[2]) * 255), 255)),
                    face_material.diffuse_color[3])

    @staticmethod
    def mesh_face_to_view_polygon(context, obj, face, face_normal,
        camera_pos, camera_dir, light_pos):
        """Converts a mesh face to the ViewPolygon class

        :param context: Context
        :type context: bpy.context
        :param obj: Object the face belongs to (required because it stores the face materials)
        :type obj: bpy.types.Object
        :param face: Face to convert
        :type face: BMFace
        :param face_normal: Normal of the face in world coordinates (NOT LOCAL COORDINATES)
        :type face_normal: float[3]
        :param camera_pos: Position of the camera
        :type camera_pos: float[3]
        :param camera_dir: Direction of the camera
        :type camera_dir: float[3]
        :param light_pos: Position of the light source in world coordinates
        :type light_pos: float[3]
        :raises ValueError: Raised when atleast one vertex of the face is behind the camera
        :return: ViewPolygon instance representing the face in viewport
        :rtype: ViewPolygon
        """
        # Gets viewport position and depth of all vertices
        verts_2d = []
        behind_flag = False
        for vert in face.verts:
            vert_loc = view3d_utils.location_3d_to_region_2d(context.region,
                                                            context.space_data.region_3d,
                                                            vert.co)
            # If vertex is behind the camera, sets the flag and breaks the cycle
            if vert_loc is None:
                behind_flag = True
                break

            vert_depth = distance_point_to_plane(vert.co, camera_pos, camera_dir)

            verts_2d.append((vert_loc[0],
                             context.region.height - vert_loc[1],
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
                vert_loc = view3d_utils.location_3d_to_region_2d(context.region,
                                                                context.space_data.region_3d,
                                                                vert)
                # If vertex is behind the camera, ignores it
                if vert_loc is None:
                    continue

                vert_depth = distance_point_to_plane(vert, camera_pos, camera_dir)

                verts_2d.append((vert_loc[0],
                                context.region.height - vert_loc[1],
                                vert_depth))

        # Clips the 2D polygon
        verts_2d = ViewPortClipping.clip_2d_polygon(context, verts_2d)
        if verts_2d is None:
            # All vertices are outside the view
            return None

        # Gets material of this face
        face_material = None
        if len(obj.material_slots) != 0:
            face_material = obj.material_slots[face.material_index].material

        # Calculates color of the face
        face_color = MeshConverter.get_face_color(context,
                                                  face, face_normal, face_material,
                                                  light_pos)

        depth = distance_point_to_plane(face.calc_center_median(), camera_pos, camera_dir)

        return ViewPolygon(verts_2d,
                            depth,
                            (face_color[0], face_color[1], face_color[2]),
                            face_color[3], set_bounds=True)

    @staticmethod
    def mesh_to_view_polygons(context, obj, camera_pos, camera_dir, light_pos, view_polygons):
        """Converts the object into ViewPolygon instances and appends them to view_polygons

        :param context: context
        :type context: bpy.context
        :param obj: Object to convert
        :type obj: bpy.types.Object
        :param camera_pos: Position of the camera
        :type camera_pos: float[3]
        :param camera_dir: Direction of the camera
        :type camera_dir: float[3]
        :param light_pos: Position of the light source in world coordinates
        :type light_pos: float[3]
        :param view_polygons: Existing list of ViewPolygon instances to append new instances to
        :type view_polygons: List of ViewPolygon
        :raises ValueError: Raised at the end if any vertex of the object was behind the camera
        """
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
            if context.scene.export_properties.backface_culling and \
                MeshConverter.is_backface(face, face_normal_world, camera_pos):
                # Culls backfaces
                continue

            view_polygon = MeshConverter.mesh_face_to_view_polygon(context, obj,
                                                                    face, face_normal_world,
                                                                    camera_pos, camera_dir,
                                                                    light_pos)
            if view_polygon is not None:
                view_polygons.append(view_polygon)


        # Frees the copied mesh
        obj_mesh.free()

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
        if sorting_heuristic == "heuristic.bbmid":
            view_polygons.sort(key = lambda polygon: (polygon.bounds[5] + polygon.bounds[4]) / 2.0,
                               reverse = True)
        elif sorting_heuristic == "heuristic.bbmin":
            view_polygons.sort(key = lambda polygon: polygon.bounds[4], reverse = True)
        elif sorting_heuristic == "heuristic.bbmax":
            view_polygons.sort(key = lambda polygon: polygon.bounds[5], reverse = True)
        elif sorting_heuristic == "heuristic.weightmid":
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
    def in_conflict(polygon_p, polygon_q):
        """Checks whether two polygons are conflicting

        :param polygon_p: Polygon p
        :type polygon_p: ViewPolygon
        :param polygon_q: Polygon q
        :type polygon_q: ViewPolygon
        :return: Returns true if polygons are in conflict, false otherwise
        :rtype: bool
        """
        p_bounds = polygon_p.bounds
        q_bounds = polygon_q.bounds

        # If there is no overlap on z bounds, no collision
        # (PzMin and PzMax > QzMax) or (PzMin and PzMax < QzMin)
        if (p_bounds[4] > q_bounds[5] and p_bounds[5] > q_bounds[5]) or\
           (p_bounds[4] < q_bounds[4] and p_bounds[5] < q_bounds[4]):
            return False

        # If there is no overlap on y bounds, no collision
        # (PyMin and PyMax > QyMax) or (PyMin and PyMax < QyMin)
        if (p_bounds[2] > q_bounds[3] and p_bounds[3] > q_bounds[3]) or\
           (p_bounds[2] < q_bounds[2] and p_bounds[3] < q_bounds[2]):
            return False

        # If there is no overlap on x bounds, no collision
        # (PxMin and PxMax > QxMax) or (PxMin and PxMax < QxMin)
        if (p_bounds[0] > q_bounds[1] and p_bounds[1] > q_bounds[1]) or\
           (p_bounds[0] < q_bounds[0] and p_bounds[1] < q_bounds[0]):
            return False

        # If p does not collide with q's plane, no collision
        if DepthSorter.relative_pos(polygon_q, polygon_p) != 0:
            return False

        # If q does not collide with p's plane, no collision
        if DepthSorter.relative_pos(polygon_p, polygon_q) != 0:
            return False

        # If p and q projections do not overlap, no collision
        p_proj_verts = list()
        for vert in polygon_p.verts:
            p_proj_verts.append((vert[0], vert[1]))
        q_proj_verts = list()
        for vert in polygon_q.verts:
            q_proj_verts.append((vert[0], vert[1]))
        if not ShapelyPolygon(p_proj_verts).overlaps(ShapelyPolygon(q_proj_verts)):
            return False

        # If bounding boxes collide, both polygons collide with each other's plane
        # and their projections overlap => collision detected
        return True

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
    def view_polygon_to_svg_string(view_polygon, precision):
        """Converts a ViewPolygon instance to a string in svg format

        :param view_polygon: Converted polygon
        :type view_polygon: ViewPolygon
        :param precision: Number of decimal places for coordinates (1-15)
        :type precision: int
        :return: String in svg format defining the ViewPolygon
        :rtype: str
        """
        polygon_string = "   <polygon points=\""

        # Prints 2D vertices in a sequence as a polygon
        for vert in view_polygon.verts:
            polygon_string += f"{round(vert[0], precision)},{round(vert[1], precision)} "

        # Sets the colour and opacity of the polygons
        polygon_string += f"\" fill=\"rgb({int(view_polygon.rgb_color[0])},"\
            f"{int(view_polygon.rgb_color[1])},"\
            f"{int(view_polygon.rgb_color[2])})\""\
            f" stroke="\
            f"\"rgb({int(view_polygon.stroke_color[0])},"\
            f"{int(view_polygon.stroke_color[1])},"\
            f"{int(view_polygon.stroke_color[2])})\""

        if view_polygon.opacity != 1.0:
            polygon_string += f" fill-opacity=\"{round(view_polygon.opacity, 4)}\" "
        if view_polygon.stroke_opacity != 1.0:
            polygon_string += f" stroke-opacity=\"{round(view_polygon.stroke_opacity, 4)}\" />\n"
        else:
            polygon_string += f" />\n"
            
        return polygon_string

    @staticmethod
    def gen_svg_head(f, context):
        """Generates svg head and writes it to the file

        :param f: File descriptor of the svg file
        :type f: file object
        :param context: Context
        :type context: bpy.context
        """
        f.write(f"<svg width=\"{context.region.width}\" height=\"{context.region.height}\"" + \
                f" stroke-width=\"{context.scene.export_properties.stroke_width}\"" + \
                " stroke-linejoin=\"round\"" + \
                " version=\"1.1\" xmlns=\"http://www.w3.org/2000/svg\">\n\n")

        group_name = "model_to_svg_group"
        f.write(" <g id=\"" + group_name + "\">\n")

    @staticmethod
    def gen_svg_body(f, context):
        """Generates svg body and writes it to the file

        :param f: File descriptor of the svg file
        :type f: file object
        :param context: Context
        :type context: bpy.context
        """
        global STARTTIME
        STARTTIME = datetime.now()
        view_polygons = []

        # Gets camera and light positions/properties
        camera_pos = view3d_utils.region_2d_to_origin_3d(bpy.context.region,
                                                         context.space_data.region_3d,
                                                         (context.region.width / 2,
                                                          context.region.height / 2))

        camera_dir = context.space_data.region_3d.view_location - camera_pos

        light_pos = camera_pos
        if not context.scene.export_properties.camera_light:
            for obj in context.selected_objects:
                if obj.type == "LIGHT":
                    light_pos = obj.location
                    break

        # Recalculates planar light direction to world coordinates
        if not context.scene.export_properties.point_light:
            result_dir = Vector((context.scene.export_properties.light_direction[0],
                                 context.scene.export_properties.light_direction[1],
                                 context.scene.export_properties.light_direction[2]))
            result_dir.rotate(context.space_data.region_3d.view_rotation)
            context.scene.export_properties.world_light_dir = (result_dir[0],
                                                               result_dir[1],
                                                               result_dir[2])

        # Converts all objects to ViewPolygon instances and adds them to the list
        for obj in context.selected_objects:
            if obj.type == "MESH":
                MeshConverter.mesh_to_view_polygons(context,
                                                    obj,
                                                    camera_pos, camera_dir,
                                                    light_pos,
                                                    view_polygons)

        print("Converted all meshes to view polygons... ", (datetime.now() - STARTTIME).total_seconds())
        STARTTIME = datetime.now()

        # Reads precision and override options
        coord_precision = context.scene.export_properties.coord_precision
        stroke_color = None
        if context.scene.export_properties.custom_strokes:
            stroke_color = (int(context.scene.export_properties.stroke_color[0] * 255),
                            int(context.scene.export_properties.stroke_color[1] * 255),
                            int(context.scene.export_properties.stroke_color[2] * 255),
                            context.scene.export_properties.stroke_color[3])    

        # Resolves conflicts and sorts based on settings
        if not context.scene.export_properties.cut_conflicts:
            # Sorts the viewport polygons based on their depth attribute
            DepthSorter.depth_sort_bb_depth(view_polygons,
                                            context.scene.export_properties.sorting_heuristic)

            print("Quickly depth sorted... ", (datetime.now() - STARTTIME).total_seconds())
            STARTTIME = datetime.now()

            # Converts all the viewport polygons to svg formatted strings and writes them
            for polygon in view_polygons:
                # Overrides stroke color if customized
                if stroke_color is not None:
                    polygon.stroke_color = stroke_color[0:3]
                    polygon.stroke_opacity = stroke_color[3]
                f.write(SVGFileGenerator.view_polygon_to_svg_string(polygon, coord_precision))

            print("Saved all polygons to file... ", (datetime.now() - STARTTIME).total_seconds())
            STARTTIME = datetime.now()
        else:
            # Corrects normals of polygons so that all face the camera
            DepthSorter.correct_normals(view_polygons, (context.region.width / 2.0,
                                                        context.region.height / 2.0,
                                                        0))

            # BSP tree sort
            root = DepthSorter.depth_sort_bsp(view_polygons,
                    context.scene.export_properties.partition_cycles_limit)

            print("Created BSP tree... ", (datetime.now() - STARTTIME).total_seconds())
            STARTTIME = datetime.now()

            view_polygons = list()
            DepthSorter.bsp_tree_to_view_polygons(root, view_polygons,
                                                    (context.region.width / 2.0,
                                                    context.region.height / 2.0,
                                                    0))
            print("Converted BSP tree to polygon list... ", (datetime.now() - STARTTIME).total_seconds())
            STARTTIME = datetime.now()

            # Writes polygons to the file
            for polygon in view_polygons:
                # Overrides stroke color if customized
                if stroke_color is not None:
                    polygon.stroke_color = stroke_color[0:3]
                    polygon.stroke_opacity = stroke_color[3]
                f.write(SVGFileGenerator.view_polygon_to_svg_string(polygon, coord_precision))
            print("Wrote polygons... ", (datetime.now() - STARTTIME).total_seconds())
            STARTTIME = datetime.now()

    @staticmethod
    def gen_svg_tail(f):
        """Generates svg tail and writes it to the file

        :param f: File descriptor of the svg file
        :type f: file object
        """
        f.write(" </g>\n")
        f.write("</svg>")

#
# EXPORT AND RESET OPERATOR
#

class ExportSVGOperator(bpy.types.Operator):
    """Exports selected models to the specified .svg file"""
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

        # Checks grayscale range
        if context.scene.export_properties.grayscale and \
           context.scene.export_properties.min_brightness > \
           context.scene.export_properties.max_brightness:
            display_message("Invalid grayscale brightness range", "Error", "ERROR")
            return {"FINISHED"}

        # Checks if any light source is selected
        valid_light = False
        if context.scene.export_properties.camera_light:
            valid_light = True
        else:
            for obj in context.selected_objects:
                if obj.type == "LIGHT":
                    valid_light = True
                    break
        if context.scene.export_properties.point_light and not valid_light:
            display_message("No light source has been selected", "Error", "ERROR")
            return {"FINISHED"}

        # Checks if any mesh object is selected
        valid_object = False
        for obj in context.selected_objects:
            if obj.type == "MESH":
                valid_object = True

        if not valid_object:
            display_message("No objects of type MESH have been selected", "Error", "ERROR")
            return {"FINISHED"}

        # Opens output file
        path = context.scene.export_properties.output_path
        if path[-4:] != ".svg":
            path += ".svg"

        try:
            f = open(path, "w", encoding = "utf-8")
        except FileNotFoundError:
            display_message("Output directory not found", "Error", "ERROR")
            return {"FINISHED"}
        except PermissionError:
            display_message("Permission to open file denied", "Error", "ERROR")
            return {"FINISHED"}

        # Generates output file
        SVGFileGenerator.gen_svg_head(f, context)
        print("Generated svg head... ", (datetime.now() - STARTTIME).total_seconds())
        STARTTIME = datetime.now()
        try:
            SVGFileGenerator.gen_svg_body(f, context)
        except ValueError as e:
            traceback.print_exc()
        except RecursionError as e:
            SVGFileGenerator.gen_svg_tail(f)
            f.close()
            limit = str(context.scene.export_properties.partition_cycles_limit)
            display_message("Partition cycles limit (" + limit + ")" +\
                            " of the BSP method reached, try using other cutting methods" + \
                            " or increasing the partition cycles limit if the memory allows it",
                            "Error", "ERROR")
            return {"FINISHED"}
        except KeyboardInterrupt as e:
            f.close()
            print("Export interrupted")
            return {"FINISHED"}

        SVGFileGenerator.gen_svg_tail(f)
        print("Generated svg tail... ", (datetime.now() - STARTTIME).total_seconds())
        print()
        STARTTIME = datetime.now()

        # Closes output file
        f.close()

        display_message("Selected models successfully exported to: " + path, "Success", "INFO")
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

        props.custom_strokes = False
        props.stroke_color = [0.0, 0.0, 0.0, 1.0]
        props.custom_fill = False
        props.fill_color = [0.5, 0.5, 0.5, 1.0]
        props.cutting_algorithm = "cut.octree"
        props.sorting_heuristic = "heuristic.bbmid"
        props.partition_cycles_limit = 500
        props.cut_conflicts = False
        props.newell_sort = False
        props.backface_culling = False
        props.grayscale = False
        props.ignore_materials = False
        props.min_brightness = 0
        props.max_brightness = 255
        props.camera_light = True
        props.point_light = False
        props.light_direction = [-0.303644, 0.259109, 0.916877]
        props.light_color = [1.0, 1.0, 1.0]
        props.ambient_color = [0.05, 0.05, 0.05]
        props.stroke_width = 0.35
        props.coord_precision = 5

        display_message("Settings have been reset to default", "Success", "INFO")

        return {"FINISHED"}

    def invoke(self, context, event):
        """Invoke method of the Reset operator
        """
        return context.window_manager.invoke_confirm(self, event)

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
        layout.label(text = "Export SVG options panel")

class ExportSVGPanelObj(ExportSVGPanel, bpy.types.Panel):
    """Object list panel class
    """
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "Selected objects:"
    bl_idname = "OBJECT_PT_export_panel_obj"

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context
        """
        layout = self.layout
        scn = context.scene

        # UI Definition

        # row = layout.row()
        # row.label(text = "Selected objects (name):")
        i = 0
        for obj in context.selected_objects:
            if obj.type == "MESH" or obj.type == "CURVE":
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

class ExportSVGPanelRender(ExportSVGPanel, bpy.types.Panel):
    """Render options panel class
    """
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "Rendering options:"
    bl_idname = "OBJECT_PT_export_panel_render"

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context
        """
        layout = self.layout
        scn = context.scene

        # UI Definition

        row = layout.row()
        row.prop(scn.export_properties, "custom_strokes")

        if context.scene.export_properties.custom_strokes:
            row = layout.row()
            row.prop(scn.export_properties, "stroke_color")

        row = layout.row()
        row.prop(scn.export_properties, "custom_fill")

        if context.scene.export_properties.custom_fill:
            row = layout.row()
            row.prop(scn.export_properties, "fill_color")

        row = layout.row()
        row.prop(scn.export_properties, "backface_culling")

        row = layout.row()
        row.prop(scn.export_properties, "cut_conflicts")

        if context.scene.export_properties.cut_conflicts:
            row = layout.row()
            row.prop(scn.export_properties, "cutting_algorithm")

            if not context.scene.export_properties.cutting_algorithm == "cut.bsp":
                row = layout.row()
                row.prop(scn.export_properties, "sorting_heuristic")
            else:
                row = layout.row()
                row.prop(scn.export_properties, "partition_cycles_limit")
        else:
            row = layout.row()
            row.prop(scn.export_properties, "sorting_heuristic")

class ExportSVGPanelLight(ExportSVGPanel, bpy.types.Panel):
    """Lighting options panel class
    """
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "Lighting options:"
    bl_idname = "OBJECT_PT_export_panel_light"

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context
        """
        layout = self.layout
        scn = context.scene

        # UI Definition

        row = layout.row()
        row.prop(scn.export_properties, "point_light")

        if context.scene.export_properties.point_light:
            row = layout.row()
            row.prop(scn.export_properties, "camera_light")

            light_found = False
            if not context.scene.export_properties.camera_light:
                row = layout.row()
                row.label(text = "Selected light source (name):")
                for obj in context.selected_objects:
                    if obj.type == "LIGHT":
                        row = layout.row()
                        row.label(text = "     " + obj.name)
                        light_found = True
                        break
                if not light_found:
                    row = layout.row()
                    row.label(text = "     NO LIGHT SELECTED")
        else:
            row = layout.row()
            row.label(text = "Planar light direction:")

            row = layout.row()
            row.prop(scn.export_properties, "light_direction")

        row = layout.row()
        row.prop(scn.export_properties, "ignore_materials")

        row = layout.row()
        row.prop(scn.export_properties, "grayscale")

        if not context.scene.export_properties.grayscale:
            row = layout.row()
            row.prop(scn.export_properties, "light_color")
            row = layout.row()
            row.prop(scn.export_properties, "ambient_color")
        else:
            row = layout.row()
            row.label(text = "Grayscale brightness range:")
            row = layout.row()
            row.prop(scn.export_properties, "min_brightness")
            row.prop(scn.export_properties, "max_brightness")

class ExportSVGPanelExport(ExportSVGPanel, bpy.types.Panel):
    """Export options panel class
    """
    bl_parent_id = "OBJECT_PT_export_panel"
    bl_label = "Export:"
    bl_idname = "OBJECT_PT_export_panel_export"

    def draw(self, context):
        """Draw method of the panel

        :param context: Context
        :type context: bpy.context
        """
        layout = self.layout
        scn = context.scene

        # UI Definition

        row = layout.row()
        row.prop(scn.export_properties, "coord_precision")
        row = layout.row()
        row.prop(scn.export_properties, "stroke_width")

        row = layout.row()
        row.label(text = "Output file path:")
        row = layout.row()
        row.prop(scn.export_properties, "output_path", text = "")

        row = layout.row()
        row.scale_y = 2
        row.operator("object.export_svg", icon = "OUTPUT")
        row = layout.row()
        row.operator("object.export_reset", icon = "FILE_REFRESH")


#
# (UN)REGISTER FUNCTIONS
#

def register():
    """ Function for registering classes
    """
    bpy.utils.register_class(ExportSVGProperties)
    bpy.types.Scene.export_properties = bpy.props.PointerProperty(type = ExportSVGProperties)
    bpy.utils.register_class(ExportSVGOperator)
    bpy.utils.register_class(ExportSVGReset)
    bpy.utils.register_class(ExportSVGPanelMain)
    bpy.utils.register_class(ExportSVGPanelObj)
    bpy.utils.register_class(ExportSVGPanelRender)
    bpy.utils.register_class(ExportSVGPanelLight)
    bpy.utils.register_class(ExportSVGPanelExport)


def unregister():
    """Function for unregistering classes
    """
    bpy.utils.unregister_class(ExportSVGProperties)
    del bpy.types.Scene.export_properties
    bpy.utils.unregister_class(ExportSVGOperator)
    bpy.utils.unregister_class(ExportSVGReset)
    bpy.utils.unregister_class(ExportSVGPanelMain)
    bpy.utils.unregister_class(ExportSVGPanelObj)
    bpy.utils.unregister_class(ExportSVGPanelRender)
    bpy.utils.unregister_class(ExportSVGPanelLight)
    bpy.utils.unregister_class(ExportSVGPanelExport)

#
# MAIN
#

if __name__ == "__main__":
    register()
