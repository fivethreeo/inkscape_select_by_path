#!/usr/bin/env python

import inkex
from inkex import PathElement, ShapeElement
from inkex.paths import CubicSuperPath, Path
from inkex.bezier import pointdistance
import numpy as np
import subprocess

import sys, os, shutil


def get_attributes(obj):
    """ Returns a string containing all object attributes
         - One attribute per line
    """
    attribute_string = 'test'
    for att in dir(obj):
        try:
            attribute = (att, getattr(obj, att))
            attribute_string = attribute_string + str(attribute) + '\n'
        except:
            None
    return attribute_string


# Platform Check
################
def os_check():
    """
    Check which OS we are using
    :return: OS Name ( windows, linux, macos )
    """
    from sys import platform

    if 'linux' in platform.lower():
        return 'linux'
    elif 'darwin' in platform.lower():
        return 'macos'
    elif 'win' in platform.lower():
        return 'windows'


# Functions to silence stderr and stdout
# Close output pipeline ( See notes at top of script )
# If they are not silenced, any messages prevent the selection passback
def set_stdout(state):
    if state == 'off':
        sys.stdout = open(os.devnull, 'w')
    else:
       pass


def set_stderr(state):
    if state == 'off':
        sys.stderr = open(os.devnull, 'w')
    else:
        pass



# import warnings
# warnings.filterwarnings("ignore")

def pass_ids_to_dbus(path_id_list_string, dbus_delay, selection_mode, current_selection_id_list_string):
    dbus_delay = str(dbus_delay)
    inkex.utils.debug(f"DBus delay: {dbus_delay}")
    inkex.utils.debug(f"Selection mode: {selection_mode}")
    inkex.utils.debug(f"Path ID list: {path_id_list_string}")
    inkex.utils.debug(f"Current selection ID list: {current_selection_id_list_string}")

    if os_check() == 'windows':

        py_exe = sys.executable
        if 'pythonw.exe' in py_exe:
            py_exe = py_exe.replace('pythonw.exe', 'python.exe')

        DETACHED_PROCESS = 0x08000000
        subprocess.Popen([py_exe, 'ink_dbus.py',  'application', 'None', 'None', path_id_list_string, dbus_delay, selection_mode, current_selection_id_list_string, 'as_subprocess'], creationflags=DETACHED_PROCESS)
    else:
        subprocess.Popen(['python3', 'ink_dbus.py', 'application', 'None', 'None', path_id_list_string, dbus_delay, selection_mode, current_selection_id_list_string, 'as_subprocess'],
                         preexec_fn=os.setpgrp, stdout=open('/dev/null', 'w'),
                         stderr=open('/dev/null', 'w'), )

class BezierIntersection(inkex.EffectExtension):

    def add_arguments(self, pars):

        pars.add_argument("--debug", type=inkex.Boolean, default=False,
                         help="Enable debug mode")
        pars.add_argument("--log_errors", type=inkex.Boolean, default=False,
                         help="Log errors to stderr")
        pars.add_argument("--method", type=str, default='touching',
                         help="Selection method: touching, enclosed")

        pars.add_argument("--t_criteria", type=str, default='bounding_box_cross',
                            help="Selection criteria for touching path: bounding_box_center, bounding_box_cross")
        pars.add_argument("--e_criteria", type=str, default='bounding_box_center',
                            help="Selection criteria for enclosed path: bounding_box_center, all_points, any_point")

        pars.add_argument("--t_include_hidden", type=inkex.Boolean, default=False, 
                         help="Include hidden/locked objects")
        pars.add_argument("--e_include_hidden", type=inkex.Boolean, default=False,
                            help="Include hidden/locked objects")

        pars.add_argument("--t_include_groups", type=inkex.Boolean, default=False,
                            help="Include groups in selection")
        pars.add_argument("--e_include_groups", type=inkex.Boolean, default=False,  
                            help="Include groups in selection")

        pars.add_argument("--dbus_delay_float", type=float, default=0.5,
                         help="Delay for DBus selection passback")

        pars.add_argument("--t_mode", type=str, default='replace',
                         help="Selection mode for touching path: replace, add, subtract")
        pars.add_argument("--e_mode", type=str, default='replace',  
                         help="Selection mode for enclosed path: replace, add, subtract")
        
        pars.add_argument("--t_selection_tolerance", type=float, default=0.0,
                            help="Tolerance for touching path selection (px)")
        pars.add_argument("--t_bezier_tolerance", type=float, default=1e-6,
                            help="Tolerance for Bezier intersection (px)")
        
        pars.add_argument("--e_bezier_tolerance", type=float, default=1e-6,
                            help="Tolerance for Bezier intersection (px)")
        
        pars.add_argument("--sample_points", type=int, default=200,
                         help="Number of sample points along path")

    def effect(self):
        if not self.options.log_errors:
            set_stdout('off')
            set_stderr('off')

        if not self.svg.selected:
            inkex.errormsg("No paths selected. Please select at least one path.")
            return
        
        path = self.svg.selected.pop()

        if not isinstance(path, PathElement):
            inkex.errormsg("Selected object is not a path. Please select a path.")
            return
        # check if the path is closed by z command in d
        d = path.get('d', '').strip()
        # count m and z commands
        m_count = d.lower().count('m')
        z_count = d.lower().count('z')
        is_closed = z_count > 0 and (m_count == z_count)
        if not is_closed and self.options.method == 'enclosed':
            inkex.errormsg("Selected path must be closed for enclosed selection method.")
            return
        # error if muliple m or z
        if m_count > 1 or z_count > 1:
            inkex.errormsg("Selected path has multiple 'm' or 'z' commands. Please select a valid path.")
            return

        csp = path.path.to_superpath()
        if path.transform:
            csp = csp.transform(path.transform)
        # Flatten to numpy arrays: [control_points][x,y][t]
        curve = self.csp_to_bezier(csp)

        layer_label = path.getparent().get('inkscape:label')

        # Make list of all objects types that can be selected
        checked_objects = ['path', 'rect', 'circle', 'ellipse', 'polygon', 'polyline', 'line', 'text', 'image', 'use']

        # Add group objects if a option is selected
        if self.options.t_include_groups or self.options.e_include_groups:
            checked_objects.append('g')

        # Make inclue_xpath of all object types
        include_xpath = '|self::svg:'.join(checked_objects)
        include_xpath = f'self::svg:{include_xpath}'
        
        # Get all objects in the current layer
        xpath = f'//svg:g[@inkscape:label="{layer_label}"]/*[{include_xpath}]'
        inkex.utils.debug(f"XPath: {xpath}")

        objects = self.svg.xpath(xpath, namespaces=inkex.NSS)
        inkex.utils.debug(f"Layer objects: {[obj.get('id') for obj in objects]}")
        # Check each object against the path

        if self.options.method == 'touching':
            # Find touching paths
            touching_objects = []
            for obj in objects:
                if not self.options.t_include_hidden:
                    if obj.get('style', '').find('display:none') != -1:
                        continue
                    if obj.get('sodipodi:insensitive') == 'true':
                        continue
                # if isinstance(obj, PathElement):
                #     csp2 = obj.path.to_superpath()
                #     curve2 = self.csp_to_bezier(csp2)
                #     intersections = self.find_intersections(curve, curve2, tol=self.options.t_bezier_tolerance, max_iter=20)
                #     if intersections:
                #         touching_objects.append(obj)
                if self.options.t_criteria == 'bounding_box_cross':
                    intersected = self.bezier_passes_trough_objects_bbox(curve, obj, tol=self.options.t_selection_tolerance, samples=self.options.sample_points)
                    if intersected:
                        touching_objects.append(obj)
                elif self.options.t_criteria == 'bounding_box_center':
                    intersected = self.bezier_passes_near_objects_bbox_center(curve, obj, tol=self.options.t_selection_tolerance, samples=self.options.sample_points)
                    if intersected:
                        touching_objects.append(obj)
            # Process results based on selection mode
            self.process_results(touching_objects)
        elif self.options.method == 'enclosed':
            # Check if the path is closed
            if not is_closed:
                inkex.errormsg("Selected path must be closed for enclosed selection method.")
                return
            # Find enclosed paths
            enclosed_objects = []
            for obj in objects:                
                if not self.options.e_include_hidden:
                    if obj.get('style', '').find('display:none') != -1:
                        continue
                    if obj.get('sodipodi:insensitive') == 'true':
                        continue

                if self.options.e_criteria == 'bounding_box_center':
                    center = obj.bounding_box().center
                    if self.point_enclosed_by_path(center, curve):
                        enclosed_objects.append(obj)
                elif self.options.e_criteria == 'all_points' or self.options.e_criteria == 'any_point':
                    bbox = obj.bounding_box()
                    bbox_points = [
                        (bbox.left, bbox.top), # Top-left
                        (bbox.right, bbox.top), # Top-right
                        (bbox.right, bbox.bottom), # Bottom-right
                        (bbox.left, bbox.bottom) # Bottom-left
                    ]
                    if self.options.e_criteria == 'all_points':
                        all_inside = all(self.point_enclosed_by_path(pt, curve) for pt in bbox_points)
                        if all_inside:
                            enclosed_objects.append(obj)
                    else:  # any_point
                        any_inside = any(self.point_enclosed_by_path(pt, curve) for pt in bbox_points)
                        if any_inside:
                            enclosed_objects.append(obj)
            # Process results based on selection mode
            self.process_results(enclosed_objects)

    def csp_to_bezier(self, csp):
        """Convert Inkscape's CubicSuperPath to 4-point Bézier segments"""
        bezier_segments = []
        for subpath in csp:
            for i in range(len(subpath)-1):
                x0, y0 = subpath[i][1]  # Start point
                x1, y1 = subpath[i][2]  # First control point
                x2, y2 = subpath[i+1][0]  # Second control point
                x3, y3 = subpath[i+1][1]  # End point
                bezier_segments.append(np.array([[x0,y0], [x1,y1], [x2,y2], [x3,y3]]))
        return bezier_segments

    def bezier_point(self, curve, t):
        """Evaluate a cubic Bézier at parameter t"""
        mt = 1 - t
        return (mt**3 * curve[0] + 3 * mt**2 * t * curve[1] 
                + 3 * mt * t**2 * curve[2] + t**3 * curve[3])

    def bezier_derivative(self, curve, t):
        """First derivative of cubic Bézier at t"""
        mt = 1 - t
        return (3 * mt**2 * (curve[1] - curve[0]) 
                + 6 * mt * t * (curve[2] - curve[1]) 
                + 3 * t**2 * (curve[3] - curve[2]))

    def find_intersections(self, curves1, curves2, tol=1e-6, max_iter=20):
        """Newton-Raphson intersection finder"""
        intersections = []
        
        # Check all segment pairs
        for seg1 in curves1:
            for seg2 in curves2:
                # Initial guesses (could be improved with bounding box checks)
                for t0 in np.linspace(0.1, 0.9, 3):
                    for s0 in np.linspace(0.1, 0.9, 3):
                        t, s = t0, s0
                        
                        for _ in range(max_iter):
                            # Current points
                            p1 = self.bezier_point(seg1, t)
                            p2 = self.bezier_point(seg2, s)
                            
                            # Function value
                            f = p1 - p2
                            
                            if np.linalg.norm(f) < tol:
                                intersections.append((float(p1[0]), float(p1[1])))
                                break
                            
                            # Jacobian matrix
                            J11 = self.bezier_derivative(seg1, t)
                            J12 = -self.bezier_derivative(seg2, s)
                            J = np.column_stack((J11, J12))
                            
                            try:
                                delta = np.linalg.solve(J, f)
                            except np.linalg.LinAlgError:
                                break
                            
                            t -= delta[0]
                            s -= delta[1]
                            
                            # Clamp to [0,1]
                            t = np.clip(t, 0, 1)
                            s = np.clip(s, 0, 1)
        
        # Merge nearby points
        unique_points = []
        for pt in intersections:
            if not any(np.linalg.norm(np.array(pt) - np.array(up)) < tol for up in unique_points):
                unique_points.append(pt)
        return unique_points

    def point_enclosed_by_path(self, point, path, tol=1e-6):
        """Check if a point is inside a path using ray-casting algorithm"""
        x, y = point
        ray = (x, y + 10000)
        bezier_ray = self.line_to_bezier((point, ray))
        intersections = self.find_intersections([bezier_ray], path, tol=tol, max_iter=20)
        return len(intersections) % 2 == 1
    
    def line_to_bezier(self, line):
        """Convert a line segment to a cubic Bézier curve with float64 control points"""
        p1, p2 = line
        return np.array([[p1[0], p1[1]], [p1[0], p1[1]], [p2[0], p2[1]], [p2[0], p2[1]]], dtype=np.float64)
                
    def bezier_passes_near(self, curve, point, tol=1e-6, samples=100):
        """Check if a Bézier curve passes near a point"""
        for seg in curve:
            for t in np.linspace(0, 1, samples):
                p = self.bezier_point(seg, t)
                if np.linalg.norm(p - point) < tol:
                    return True
        return False
    
    def bezier_passes_trough_objects_bbox(self, curve, obj, tol=1e-6, samples=100):
        """Check if a Bézier curve passes through object bounding box"""
        bbox = obj.bounding_box()
        for seg in curve:
            for t in np.linspace(0, 1, samples):
                p = self.bezier_point(seg, t)
                if (bbox.left - tol <= p[0] <= bbox.right + tol and
                    bbox.top - tol <= p[1] <= bbox.bottom + tol):
                    return True
        return False
    
    def bezier_passes_near_objects_bbox_center(self, curve, obj, tol=1e-6, samples=100):
        """Check if a Bézier curve passes any object bounding box center"""
        bbox = obj.bounding_box()
        center = bbox.center    
        if self.bezier_passes_near(curve, center, tol, samples):
            return True
        return False
    
    def process_results(self, intersections):
        """Process the results based on selection mode"""

        mode = self.options.t_mode if self.options.method == 'touching' else self.options.e_mode

        if self.options.debug:
            # show what selected objects will be selected
            if mode == 'replace':
                inkex.errormsg(f"Replacing selection with: {', '.join([obj.get('id') for obj in intersections])}")
            elif mode == 'add':
                selected_with_addition = list(set([obj.get('id') for obj in self.svg.selected] + [obj.get('id') for obj in intersections]))
                inkex.errormsg(f"New selection with addition: {', '.join(selected_with_addition)}")
            elif mode == 'subtract':
                selected_with_subtraction = [obj.get('id') for obj in self.svg.selected if obj not in intersections]
                inkex.errormsg(f"New selection with subtraction: {', '.join(selected_with_subtraction)}")
        else:
            # Pass the selected objects to DBus for selection
            path_id_list = [obj.get('id') for obj in intersections]
            current_selection_id_list = [obj.get('id') for obj in self.svg.selected]
            path_id_list_string = ','.join(path_id_list)
            current_selection_id_list_string = ','.join(current_selection_id_list)

            if mode == 'replace':
                selection_mode = 'clear'
            elif mode == 'add':
                selection_mode = 'add'
            elif mode == 'subtract':
                selection_mode = 'subtract'
                
            pass_ids_to_dbus(path_id_list_string, self.options.dbus_delay_float, selection_mode, current_selection_id_list_string)
            sys.exit(0)
            
if __name__ == '__main__':
    BezierIntersection().run()
