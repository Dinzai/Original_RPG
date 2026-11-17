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
        
    def on_battle_pressed(self):
        print("hey")
        
    def on_item_pressed(self):
        self.game.ui_set_visible(self.battleID, False)
        self.game.ui_set_visible(self.itemID, False)
        self.game.ui_set_visible(self.runID, False)
        self.game.ui_set_visible(self.itemMenuID, True)
        self.game.ui_set_visible(self.exitID, True)
    
    def on_exit_pressed(self):
        self.game.ui_set_visible(self.battleID, True)
        self.game.ui_set_visible(self.itemID, True)
        self.game.ui_set_visible(self.runID, True)
        self.game.ui_set_visible(self.itemMenuID, False)
        self.game.ui_set_visible(self.exitID, False)
        
    def on_run_pressed(self):
            chance = self.game.get_random_num(1, 3)
            if chance > 1:
                self.game.load_scene("WORLD")
            else:
                globals.turn = 1
                
            
    def on_start(self):
        self.owner.set_origin(self.owner.get_image_size().x() / 2, self.owner.get_image_size().y() / 2)
        self.owner.set_scale(3, 3)
        self.game.ui_image(320, 500, 512, 128, "Assets/UIChoiceBar.png")
        self.battleID = self.game.ui_button(345, 525, 128,32, "BATTLE", self.on_battle_pressed)
        self.itemID = self.game.ui_button(345, 575, 128,32, "ITEM", self.on_item_pressed)
        self.runID = self.game.ui_button(645, 525, 128,32, "RUN", self.on_run_pressed)
        self.itemMenuID = self.game.ui_image(345, 300, 128, 256, "Assets/UIChoiceBar.png")
        self.exitID = self.game.ui_button(645, 525, 128,32, "EXIT", self.on_exit_pressed)
        self.game.ui_set_visible(self.itemMenuID, False)
        self.game.ui_set_visible(self.exitID, False)
        

    def on_update(self, delta):
        pass

    def on_click(self):
        pass

    def on_action(self):
        pass
