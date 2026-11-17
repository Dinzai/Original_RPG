import libviper


class Behaviour:
    def __init__(self, owner, game):
        # type: (libviper.Generic, libviper.Loop) -> None
        self.owner = owner
        self.game = game
    def begin_game(self):
        self.game.load_scene("WORLD")

    def on_start(self):
        self.game.set_camera_zoom(1)
        self.game.ui_button(500,300,128,32, "PLAY", self.begin_game)

    def on_update(self, delta):
        pass

    def on_click(self):
        pass

    def on_action(self):
        pass
