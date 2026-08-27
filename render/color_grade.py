"""Post-process hue/saturation grade for the world pass.

Sim stays Arcade-free; this module owns the FBO and HSV shader.
Identity (hue 0°, sat 100%) is skipped by the caller so there is no extra cost.
"""
from __future__ import annotations

from arcade.gl import geometry

from sim.scenario import clamp_color_hue, clamp_color_sat

_VERT = """
#version 330
in vec2 in_vert;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
    v_uv = in_uv;
}
"""

_FRAG = """
#version 330
uniform sampler2D image;
uniform float u_hue;
uniform float u_sat;
in vec2 v_uv;
out vec4 fragColor;

vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c) {
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
    vec4 src = texture(image, v_uv);
    vec3 hsv = rgb2hsv(src.rgb);
    hsv.x = fract(hsv.x + u_hue);
    hsv.y = clamp(hsv.y * u_sat, 0.0, 1.0);
    fragColor = vec4(hsv2rgb(hsv), src.a);
}
"""


def is_identity_grade(hue_deg: float, sat: float) -> bool:
    """True when the grade would be a no-op (skip the extra pass)."""
    return clamp_color_hue(hue_deg) == 0 and abs(clamp_color_sat(sat) - 1.0) < 1e-9


class WorldColorGrade:
    """Window-sized FBO plus a fullscreen hue/sat blit."""

    def __init__(self, ctx):
        self.ctx = ctx
        self._size = (0, 0)
        self._tex = None
        self._fbo = None
        self._prog = ctx.program(vertex_shader=_VERT, fragment_shader=_FRAG)
        self._quad = geometry.quad_2d_fs()
        try:
            self._prog["image"] = 0
        except KeyError:
            pass

    def begin(self, width: int, height: int) -> None:
        """Bind the world FBO (nearest, window-sized). Caller draws the world next."""
        self._ensure(width, height)
        self._fbo.use()
        self._fbo.clear(color=(0, 0, 0, 0))

    def end_and_blit(self, hue_deg: float, sat: float) -> None:
        """Grade the FBO onto the default framebuffer; leave alpha alone."""
        self.ctx.screen.use()
        self._tex.use(0)
        self._prog["u_hue"] = (clamp_color_hue(hue_deg) % 360) / 360.0
        self._prog["u_sat"] = clamp_color_sat(sat)
        prev = self.ctx.blend_func
        self.ctx.blend_func = self.ctx.BLEND_DEFAULT
        self._quad.render(self._prog)
        self.ctx.blend_func = prev

    def _ensure(self, width: int, height: int) -> None:
        size = (max(1, int(width)), max(1, int(height)))
        if self._fbo is not None and self._size == size:
            return
        self._size = size
        self._tex = self.ctx.texture(
            size,
            components=4,
            filter=(self.ctx.NEAREST, self.ctx.NEAREST),
            wrap_x=self.ctx.CLAMP_TO_EDGE,
            wrap_y=self.ctx.CLAMP_TO_EDGE,
        )
        self._fbo = self.ctx.framebuffer(color_attachments=[self._tex])
