from .builder import build_base


def post_init_hook(env):
    build_base(env)
