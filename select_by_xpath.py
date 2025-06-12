#!/usr/bin/env python
"""
Select objects in Inkscape by XPath expression.

This script allows you to select objects in Inkscape based on an XPath expression or class name.
It is intended to be used as an Inkscape extension.
"""

import inkex
import subprocess

import sys, os, shutil

# print current working directory
inkex.utils.debug(f"Current working directory: {os.getcwd()}")


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
                         stderr=open('/tmp/inkdbus.txt', 'w'), )


class SelectByXPath(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument("--selection_mode", type=str, default='replace', help="Selection mode: replace or add")
        pars.add_argument("--xpath", type=str, help="XPath expression to select objects")
        pars.add_argument("--classname", type=str, help="Class name to select objects")
        pars.add_argument("--dbus_delay", type=float, default=0.1, help="Delay before sending selection to DBus")
        pars.add_argument("--debug", type=inkex.Boolean, default=False, help="Enable debug mode")

    def effect(self):
        # Set debug mode
        if not self.options.debug:
            set_stdout('off')
            set_stderr('off')

        xpath = self.options.xpath
        class_name = self.options.classname

        if xpath:
            elements = self.svg.xpath(xpath)
        elif class_name:
            elements = self.svg.xpath(f"//*[@class='{class_name}']")
        else:
            inkex.errormsg("Please provide either an XPath expression or a class name.")
            return
        if not elements:
            inkex.errormsg("No elements found matching the criteria.")
            return
        # Collect IDs of selected elements
        selected_ids = [element.get('id') for element in elements if element.get('id')]

        if not selected_ids:
            inkex.errormsg("No elements with IDs found matching the criteria.")
            return
        # Prepare the ID list as a string
        path_id_list_string = ','.join(selected_ids)
        # Set selection by DBus
        current_selection_id_list_string = ','.join([elem.get('id') for elem in self.svg.selected if elem.get('id')])
         # 'clear', 'add', or 'subtract', replace 'replace' with 'clear'
        selection_mode = self.options.selection_mode == 'replace' and 'clear' or self.options.selection_mode
        dbus_delay = self.options.dbus_delay
        # Pass IDs to DBus
        pass_ids_to_dbus(path_id_list_string, dbus_delay, selection_mode, current_selection_id_list_string)
        sys.exit(0)

if __name__ == '__main__':
    SelectByXPath().run()

