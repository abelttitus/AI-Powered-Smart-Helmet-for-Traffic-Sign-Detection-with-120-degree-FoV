# Edge Impulse - OpenMV FOMO Object Detection Example
# Modified for Smart Helmet project - sends detections over serial to Raspberry Pi
#
# This work is licensed under the MIT license.
# Copyright (c) 2013-2024 OpenMV LLC. All rights reserved.

import sensor, image, time, ml, math, uos, gc
from pyb import UART

# ── Change this for each Nicla: NICLA_1, NICLA_2, or NICLA_3 ──
DEVICE_ID = "NICLA_2"

# ── Detection confidence threshold ──
min_confidence = 0.5

# Serial to Raspberry Pi
uart = UART(1, 115200)

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.set_windowing((240, 240))
sensor.skip_frames(time=2000)

net = None
labels = None

try:
    net = ml.Model("trained.tflite", load_to_fb=uos.stat('trained.tflite')[6] > (gc.mem_free() - (64*1024)))
except Exception as e:
    raise Exception('Failed to load "trained.tflite" (' + str(e) + ')')

try:
    labels = [line.rstrip('\n') for line in open("labels.txt")]
except Exception as e:
    raise Exception('Failed to load "labels.txt" (' + str(e) + ')')

colors = [
    (255,   0,   0),
    (  0, 255,   0),
    (255, 255,   0),
    (  0,   0, 255),
    (255,   0, 255),
    (  0, 255, 255),
    (255, 255, 255),
]

threshold_list = [(math.ceil(min_confidence * 255), 255)]

def fomo_post_process(model, inputs, outputs):
    ob, oh, ow, oc = model.output_shape[0]

    x_scale = inputs[0].roi[2] / ow
    y_scale = inputs[0].roi[3] / oh

    scale = min(x_scale, y_scale)

    x_offset = ((inputs[0].roi[2] - (ow * scale)) / 2) + inputs[0].roi[0]
    y_offset = ((inputs[0].roi[3] - (ow * scale)) / 2) + inputs[0].roi[1]

    l = [[] for i in range(oc)]

    # Edge Impulse int8 FOMO standard quantization params
    output_scale = 1.0 / 128.0
    output_zero_point = -128

    for i in range(oc):
        raw = outputs[0][0, :, :, i]

        for y in range(oh):
            for x in range(ow):
                score = (int(raw[y][x]) - output_zero_point) * output_scale
                score = min(1.0, max(0.0, score))

                if score >= min_confidence:
                    x_mapped = int((x * scale) + x_offset)
                    y_mapped = int((y * scale) + y_offset)
                    w_mapped = int(scale)
                    h_mapped = int(scale)
                    l[i].append((x_mapped, y_mapped, w_mapped, h_mapped, score))
    return l

clock = time.clock()
while True:
    clock.tick()

    img = sensor.snapshot()

    for i, detection_list in enumerate(net.predict([img], callback=fomo_post_process)):
        if i == 0: continue          # skip background
        if len(detection_list) == 0: continue

        label = labels[i]

        # Pick the highest scoring detection for this class
        best_score = max(detection_list, key=lambda d: d[4])
        x, y, w, h, score = best_score

        # Draw on frame
        center_x = math.floor(x + (w / 2))
        center_y = math.floor(y + (h / 2))
        img.draw_circle((center_x, center_y, 12), color=colors[i])

        # Send over serial to Pi: DEVICE_ID:label:score
        msg = "%s:%s:%.2f\n" % (DEVICE_ID, label, score)
        uart.write(msg)
