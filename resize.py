from PIL import Image
import os

input_folder = "images"
output_folder = "center_padded"

os.makedirs(output_folder, exist_ok=True)

size = (300, 300)  # final frame size

def center_pad(img):
    img.thumbnail((200, 200))  # make image smaller inside frame

    new_img = Image.new("RGB", size, (255, 255, 255))  # white background

    x = (size[0] - img.size[0]) // 2
    y = (size[1] - img.size[1]) // 2

    new_img.paste(img, (x, y))

    return new_img

for file in os.listdir(input_folder):
    if file.lower().endswith((".jpg", ".jpeg", ".png")):
        img = Image.open(os.path.join(input_folder, file))

        result = center_pad(img)

        result.save(os.path.join(output_folder, file))

print("Done! Images centered with padding.")