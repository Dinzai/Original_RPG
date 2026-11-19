import libviper

import sys
from pathlib import Path

script_dir = str(Path(__file__).resolve().parent)
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

import globals

class Behaviour:
    def __init__(self, owner, game):
        # type: (libviper.Generic, libviper.Loop) -> None
        self.owner = owner
        self.game = game
    def begin_game(self):
        self.game.load_scene("WORLD")
        
    def check_game(self):
        self.game.load_scene("GUIDE")

    def on_start(self):
        self.playID = self.game.ui_button(500,300,128,32, "PLAY", self.begin_game)
        self.guideID = self.game.ui_button(500,500,128,32, "GUIDE", self.check_game)
        
        self.game.ui_set_colour(self.playID, globals.light_color)
        self.game.ui_set_text_colour(self.playID, globals.dark_color)
                
        self.game.ui_set_colour(self.guideID, globals.light_color)
        self.game.ui_set_text_colour(self.guideID, globals.dark_color)

    def on_update(self, delta):
        pass

    def on_click(self):
        pass

    def on_action(self):
        pass
