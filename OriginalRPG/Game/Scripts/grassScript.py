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
        owner.bind_trigger_script(self)

    def on_start(self):
        self.game.remove_collision(self.owner)


    def on_update(self, delta):
        self.owner.play_anim(0, 3)

    def on_trigger_enter(self):
        # self.owner.get_trigger_object_id() identifies the other object.
        pass

    def on_trigger_stay(self):
        pass

    def on_trigger_exit(self):
        pass
