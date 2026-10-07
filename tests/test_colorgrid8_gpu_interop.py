"""Offline execution of Android's sampling shader on a Desktop GL context.

Opt in with SUPERQR_COLORGRID_GPU_TESTS=1 and SUPERQR_COLORGRID_DECODER.
Requires PyOpenGL in the test environment (not a product dependency). The only
shader adaptations are GLES -> desktop GLSL and OES -> a regular 2D texture.
This checks GPU coordinates/readback against the native decoder, not phone
camera capture, Android drivers, optical reliability, or physical throughput.
"""
import ctypes
import os
from pathlib import Path
import re

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SUPERQR_COLORGRID_GPU_TESTS") != "1",
    reason="optional offline GPU regression not enabled",
)


@pytest.fixture(scope="module")
def gpu():
    import pygame
    from OpenGL import GL as gl
    from OpenGL.GL.shaders import compileProgram, compileShader

    path = Path(__file__).resolve().parents[2] / "superqr-android/vision/src/main/java/com/superqr/android/vision/lab/colorgrid8/gl/ColorGrid8GlShaders.kt"
    source = path.read_text(encoding="utf-8")

    def shader(name):
        code = re.search(r'const val ' + name + r' = """(.*?)"""', source, re.S)[1]
        code = code.replace("#version 300 es", "#version 330 core")
        code = re.sub(r"\s*#extension[^\n]*", "", code)
        return code.replace("samplerExternalOES", "sampler2D")

    pygame.display.init()
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
    pygame.display.set_mode((32, 32), pygame.OPENGL | pygame.HIDDEN)
    program = compileProgram(compileShader(shader("PASSTHROUGH_VERTEX"), gl.GL_VERTEX_SHADER),
                             compileShader(shader("CELL_SAMPLE_FRAGMENT"), gl.GL_FRAGMENT_SHADER))
    vao = gl.glGenVertexArrays(1)
    vbo = gl.glGenBuffers(1)
    fbo = gl.glGenFramebuffers(1)
    input_tex, output_tex = gl.glGenTextures(2)
    gl.glBindVertexArray(vao)
    gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
    quad = np.float32([[-1, -1, 0, 1], [1, -1, 1, 1], [-1, 1, 0, 0], [1, 1, 1, 0]])
    gl.glBufferData(gl.GL_ARRAY_BUFFER, quad.nbytes, quad, gl.GL_STATIC_DRAW)
    for index in (0, 1):
        gl.glEnableVertexAttribArray(index)
        gl.glVertexAttribPointer(index, 2, gl.GL_FLOAT, False, 16, ctypes.c_void_p(index * 8))

    def render(rgb, homographies, *, header=False, offset=(0, 0), sample_mode=1, dims=(336, 288)):
        height, width, _ = rgb.shape
        out_w, out_h = (112, 200) if header else dims
        gl.glUseProgram(program)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, input_tex)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB8, width, height, 0, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, rgb)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glBindTexture(gl.GL_TEXTURE_2D, output_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, out_w, out_h, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D, output_tex, 0)
        assert gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) == gl.GL_FRAMEBUFFER_COMPLETE
        gl.glBindTexture(gl.GL_TEXTURE_2D, input_tex)
        loc = lambda name: gl.glGetUniformLocation(program, name)
        # Upload has row zero first. Model SurfaceTexture's vertical transform;
        # Android's shader still executes its actual camera-coordinate flip.
        transform = np.float32([[1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]])
        gl.glUniformMatrix4fv(loc("uTexMatrix"), 1, False, transform.T.copy())
        gl.glUniformMatrix3fv(loc("uHomography"), 1, False, homographies[0].T.copy())
        gl.glUniformMatrix3fv(loc("uHeaderHomographies[0]"), 4, False,
                             np.stack([h.T for h in homographies]).astype(np.float32))
        gl.glUniform1i(loc("uTexture"), 0)
        gl.glUniform1i(loc("uHeaderSearch"), int(header))
        gl.glUniform1i(loc("uSampleMode"), sample_mode)
        gl.glUniform1i(loc("uFiducialOffset"), 8)
        gl.glUniform2f(loc("uCameraSize"), width, height)
        gl.glUniform2f(loc("uCellOffset"), *offset)
        gl.glViewport(0, 0, out_w, out_h)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        raw = gl.glReadPixels(0, 0, out_w, out_h, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
        assert gl.glGetError() == gl.GL_NO_ERROR
        return np.frombuffer(raw, np.uint8).reshape(out_h, out_w, 4)[..., :3].transpose(2, 0, 1).copy()

    yield render
    gl.glDeleteFramebuffers(1, [fbo])
    gl.glDeleteTextures([input_tex, output_tex])
    gl.glDeleteBuffers(1, [vbo])
    gl.glDeleteVertexArrays(1, [vao])
    gl.glDeleteProgram(program)
    pygame.display.quit()


@pytest.mark.parametrize("rotation", range(4))
@pytest.mark.parametrize("offset", [(0, 0), (0.5, 0.5)])
@pytest.mark.parametrize("dims", [(240, 216), (336, 288)])
def test_header_atlas_and_payload_use_same_coordinates(gpu, tmp_path, rotation, offset, dims):
    import cv2
    import pygame
    from test_colorgrid8_native_interop import decode
    from superqr_desktop.lab.colorgrid8_core import ColorGrid8Profile
    from superqr_desktop.lab.colorgrid8_renderer import ColorGrid8Renderer
    from superqr_desktop.lab.colorgrid8_transfer import ColorGrid8TransferSession, symbols_to_bytes, parse_transport_frame

    path = tmp_path / "gpu.bin"
    path.write_bytes(bytes(range(251)) * 31)
    profile = ColorGrid8Profile(*dims, 30, version=2)
    with ColorGrid8TransferSession(path, profile) as session:
        symbols = session.symbol_frame(7)
        surface, geometry = ColorGrid8Renderer().render_symbols(profile, symbols, 1856, 984)
        rgb = pygame.surfarray.array3d(surface).transpose(1, 0, 2).copy()
        w, h = profile.cols + 16, profile.rows + 16
        canonical = np.float32([(0, 0), (w, 0), (w, h), (0, h)])
        corners = np.float32(geometry.fiducial_centers)
        shift = np.float32([[1, 0, offset[0]], [0, 1, offset[1]], [0, 0, 1]])
        matrices = [cv2.getPerspectiveTransform(canonical, np.roll(corners, rotation - r, axis=0)) @ shift
                    for r in range(4)]
        atlas = gpu(rgb, matrices, header=True)
        dx, dy = -offset[0], -offset[1]
        candidate = rotation * 25 + round((dy + 0.5) * 4) * 5 + round((dx + 0.5) * 4)
        ordered = [matrices[rotation]] * 4
        planes = gpu(rgb, ordered, offset=(dx, dy), dims=dims)
        np.testing.assert_array_equal(atlas[:, candidate * 2:candidate * 2 + 2], planes[:, :2, :112])
        stats, payload = decode(planes, profile)
        assert stats[:4] == (1, 6, 7, 0)
        transport = parse_transport_frame(profile, symbols_to_bytes(payload))
        assert transport is not None
        # Compare bytes, not just successful header or payload CRC recognition.
        from superqr_desktop.lab.colorgrid8_core import is_pilot
        expected = np.asarray([symbols[r, c] for r in range(2, profile.rows)
                               for c in range(profile.cols) if not is_pilot(profile, r, c)])
        np.testing.assert_array_equal(payload, expected)
        if offset != (0, 0):
            # This is a real regression case: the uncorrected sampling must not
            # already recover those exact bytes, or the test proves no recovery.
            bad_stats, bad_payload = decode(gpu(rgb, ordered, dims=dims), profile)
            assert bad_stats[0] == 0 or not np.array_equal(bad_payload, expected)
