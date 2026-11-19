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
    
    def back_to_title(self):
        self.game.load_scene("TITLE")

    def on_start(self):
        self.owner.set_origin(self.owner.get_image_size().x() / 2, self.owner.get_image_size().y() / 2)
        self.owner.set_scale(10, 10)
        self.game.ui_button(500,600,128,32, "Return", self.back_to_title)

    def on_update(self, delta):
        self.game.draw_text("Welcome to an Original RPG!", 280, 10, 55, globals.dark_color)
        self.game.draw_text("In Game, press the m key for the menu", 300, 100, 20, globals.dark_color)
        self.game.draw_text("This is only the demo, and there's not a", 300, 140, 20, globals.dark_color)
        self.game.draw_text("lot of content, however, you can battle", 300, 160, 20, globals.dark_color)
        self.game.draw_text("and explore an interesting environment", 300, 180, 20, globals.dark_color)
        self.game.draw_text("This game was made in my Game Engine, with Raylib and TGUI", 300, 200, 20, globals.dark_color)
        self.game.draw_text("VIPER ENGINE", 300, 250, 55, globals.dark_color)
        self.game.draw_text("Thank you for playing!", 300, 400, 55, globals.dark_color)
        self.game.draw_text("-Brett Rogers", 700, 600, 20, globals.dark_color)
        

    def on_click(self):
        pass

    def on_action(self):
        pass
