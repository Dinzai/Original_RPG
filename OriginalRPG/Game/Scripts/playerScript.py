import libviper

import math

import sys
from pathlib import Path

script_dir = str(Path(__file__).resolve().parent)
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

import globals

class Behaviour:
    def __init__(self, owner, game):
        # type: (libviper.Player, libviper.Loop) -> None
        self.owner = owner
        self.game = game
    
    def open_menu(self):
        if self.menu_closed == True:
            self.game.ui_set_visible(self.darkPanelID, True)
            self.game.ui_set_visible(self.lightPanelID, True)
            self.game.ui_set_visible(self.healthPanelID, True)
            self.game.ui_set_visible(self.saveButtonID, True)
            self.owner.set_speed(0)
            self.menu_closed = False
        else:
            self.game.ui_set_visible(self.darkPanelID, False)
            self.game.ui_set_visible(self.lightPanelID, False)
            self.game.ui_set_visible(self.healthPanelID, False)
            self.game.ui_set_visible(self.saveButtonID, False)
            self.owner.set_speed(35)
            self.menu_closed = True
            
    
    def save_game(self):
        pass

    def on_start(self):
        self.menu_closed = True
        self.owner.define_key("M", self.open_menu)
        self.owner.set_origin(self.owner.get_image_size().x() / 2, self.owner.get_image_size().y() / 2)
        self.owner.set_scale(0.5, 0.5)
        self.game.set_camera_zoom(0.25)
        self.owner.set_speed(35)
        globals.player_start_pos = self.owner.get_position()
        self.owner.set_movement_frames(0,3,0,3,0,3,0,3)
        self.darkPanelID = self.game.ui_panel(650, 200, 100, 200, globals.dark_color)
        self.lightPanelID = self.game.ui_panel(660, 210, 80, 180, globals.light_color)
        self.healthPanelID = self.game.ui_panel(660, 210, 60, 20, globals.light_color)
        self.game.ui_set_text(self.healthPanelID, "HP: " + str(globals.player_current_health))
        self.game.ui_set_text_colour(self.healthPanelID, globals.dark_color)
        self.saveButtonID = self.game.ui_button(662, 240, 60, 20, "SAVE", self.save_game)
        self.game.ui_set_colour(self.saveButtonID, globals.light_color)
        self.game.ui_set_text_colour(self.saveButtonID, globals.dark_color)
        
        self.game.ui_set_visible(self.darkPanelID, False)
        self.game.ui_set_visible(self.lightPanelID, False)
        self.game.ui_set_visible(self.healthPanelID, False)
        self.game.ui_set_visible(self.saveButtonID, False)
        
        if globals.enemy_intangible_after_run:
            self.game.get_player().set_position(globals.player_current_pos_x, globals.player_current_pos_y)


    def on_update(self, delta):
        pass

    def on_click(self):
        pass

    def on_action(self):
        pass
