#!/usr/bin/env python
# vim: set noai ts=4 sw=4 expandtab

# Stable Gimpfusion 
# v1.0.14
# Thin API client for Automatic1111's StableDiffusion API
# https://github.com/AUTOMATIC1111/stable-diffusion-webui

import base64
import json
import os
import random
import tempfile
import logging
import urllib
import urllib2

import gimp
import gimpenums
import gimpfu

VERSION = 14
PLUGIN_NAME = "StableGimpfusion"
PLUGIN_VERSION_URL = "https://raw.githubusercontent.com/ArtBIT/stable-gimpfusion/main/version.json"
MAX_BATCH_SIZE = 20

# Initialize debugging
if os.environ.get('DEBUG'):
    DEBUG = True
    logging.basicConfig(level=logging.DEBUG)
else:
    DEBUG = False
    logging.basicConfig(level=logging.INFO)

logging.info("StableGimfusion version %d" % VERSION)


# GLOBALS
layer_counter = 1
settings = None
api = None
models = None
sd_model_checkpoint = None
is_server_running = False


STABLE_GIMPFUSION_DEFAULT_SETTINGS = {
        "sampler_name": "Euler a",
        "denoising_strength": 0.8,
        "cfg_scale": 7.5,
        "steps": 50,
        "width": 512,
        "height": 512,
        "prompt": "",
        "negative_prompt": "",
        "batch_size": 1,
        "mask_blur": 4,
        "seed": -1,
        "api_base": "http://127.0.0.1:7860",
        "model": "",
        "models": [],
        "cn_models": [],
        "sd_model_checkpoint": None,
        "is_server_running": False
        }

RESIZE_MODES = {
        "Just Resize": 0,
        "Crop And Resize": 1,
        "Resize And Fill": 2,
        "Just Resize (Latent Upscale)": 3
        }

CONTROL_MODES = {
    "Balanced": 0,
    "My prompt is more important": 1,
    "ControlNet is more important": 2,
}

SAMPLERS = [
      "Euler a",
      "Euler",
      "LMS",
      "Heun",
      "DPM2",
      "DPM2 a",
      "DPM++ 2S a",
      "DPM++ 2M",
      "DPM++ SDE",
      "DPM fast",
      "DPM adaptive",
      "LMS Karras",
      "DPM2 Karras",
      "DPM2 a Karras",
      "DPM++ 2S a Karras",
      "DPM++ 2M Karras",
      "DPM++ SDE Karras",
      "DDIM"
    ]

CONTROLNET_RESIZE_MODES = [
        "Just Resize",
        "Scale to Fit (Inner Fit)",
        "Envelope (Outer Fit)",
        ]

CONTROLNET_MODULES = [
        "none",
        "canny",
        "depth",
        "depth_leres",
        "hed",
        "mlsd",
        "normal_map",
        "openpose",
        "openpose_hand",
        "clip_vision",
        "color",
        "pidinet",
        "scribble",
        "fake_scribble",
        "segmentation",
        "binary"
        ]

CONTROLNET_DEFAULT_SETTINGS = {
      "input_image": "",
      "mask": "",
      "module": "none",
      "model": "none",
      "weight": 1.0,
      "resize_mode": "Scale to Fit (Inner Fit)",
      "lowvram": False,
      "processor_res": 64,
      "threshold_a": 64,
      "threshold_b": 64,
      "guidance": 1.0,
      "guidance_start": 0.0,
      "guidance_end": 1.0,
      "control_mode": 0,
    }

GENERATION_MESSAGES = [
        "Making happy little pixels...",
        "Fetching pixels from a digital art museum...",
        "Waiting for bot-painters to finish...",
        "Waiting for the prompt to bake...",
        "Fetching random pixels from the internet",
        "Taking a random screenshot from an AI dream",
        "Throwing pixels at screen and seeing what sticks",
        "Converting random internet comment to RGB values",
        "Computer make pretty picture, you happy.",
        "Computer is hand-painting pixels...",
        "Turning the Gimp knob up to 11...",
        "Pixelated dreams come true, thanks to AI.",
        "AI is doing its magic...",
        "Pocket Picasso is speed-painting...",
        "Instant Rembrandt! Well, relatively instant...",
        "Doodle buddy is doing its thing...",
        "Waiting for the digital paint to dry..."
        ]


def roundToMultiple(value, multiple):
    return multiple * round(float(value)/multiple)

def deunicodeDict(data):
    """Recursively converts dictionary keys to strings."""
    if isinstance(data, unicode):
        return str(data)
    if not isinstance(data, dict):
        return data
    return dict((str(k), deunicodeDict(v)) 
        for k, v in data.items())

class ApiClient():
    """ Simple API client used to interface with StableDiffusion JSON endpoints """
    def __init__(self, base_url):
        self.setBaseUrl(base_url)

    def setBaseUrl(self, base_url):
        self.base_url = base_url

    def post(self, endpoint, data={}, params={}, headers=None):
        try:
            url = self.base_url + endpoint + "?" + urllib.urlencode(params)
            logging.debug("POST %s" % url)
            data = json.dumps(data)

            logging.debug('post data %s', data)

            headers = headers or {"Content-Type": "application/json", "Accept": "application/json"}
            request = urllib2.Request(url=url, data=data, headers=headers)
            response = urllib2.urlopen(request)
            data = response.read()
            data = json.loads(data)

            logging.debug('response: %s', data)
            return data
        except Exception as ex:
            logging.exception("ERROR: ApiClient.post")

    def get(self, endpoint, params={}, headers=None):
        try:
            url = self.base_url + endpoint + "?" + urllib.urlencode(params)
            logging.debug("POST %s" % url)
            headers = headers or {"Content-Type": "application/json", "Accept": "application/json"}
            request = urllib2.Request(url=url, headers=headers)
            response = urllib2.urlopen(request)
            data = response.read()
            data = json.loads(data)
            return data
        except Exception as ex:
            logging.exception("ERROR: ApiClient.get")


""" Get the StableDiffusion data needed for dynamic gimpfu.PF_OPTION lists """
def fetch_stablediffusion_options():
    global api, settings
    try:
        options = deunicodeDict(api.get("/sdapi/v1/options") or {})
        sd_model_checkpoint = options.get("sd_model_checkpoint", None)
        models = map(lambda data: data["title"], api.get("/sdapi/v1/sd-models") or [])
        cn_models = (api.get("/controlnet/model_list") or {}).get("model_list", [])
        cn_models = ["None"] + cn_models

        settings.save({"models": models,
            "cn_models": cn_models,
            "sd_model_checkpoint": sd_model_checkpoint,
            "is_server_running": True})
    except Exception as ex:
        logging.exception("ERROR: DynamicDropdownData.fetch")
        settings.save({"is_server_running", False})

# We need persistent data before the gimp system has initialized so we cannot use parasites nor gimpshelf
class MyShelf():
    """ GimpShelf is not available at init time, so we keep our persistent data in a json file """
    def __init__(self, default_shelf = {}):
        self.file_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'stable_gimpfusion.json')
        self.load(default_shelf)

    def load(self, default_shelf = {}):
        self.data = default_shelf
        try:
            if os.path.isfile(self.file_path):
                logging.info("Loading shelf from %s" % self.file_path)
                with open(self.file_path, "r") as f:
                    self.data = json.load(f)
                logging.info("Successfully loaded shelf")
        except Exception as e:
            logging.debug(e)

    def save(self, data = {}):
        try:
            self.data.update(data)
            logging.info("Saving shelf to %s" % self.file_path)
            with open(self.file_path, "w") as f:
                json.dump(self.data, f)
            logging.info("Successfully saved shelf")

        except Exception as e:
            logging.debug(e)


    def get(self, name, default_value=None):
        if name in self.data:
            return self.data[name]
        return default_value

    def set(self, name, default_value=None):
        self.data[name] = default_value
        self.save()

class StableGimpfusionPlugin():
    def __init__(self, image):
        global settings,api
        self.name = "stable_gimpfusion"
        self.image = image

        global is_server_running
        if not is_server_running:
            gimp.pdb.gimp_message("It seems that StableDiffusion is not runing on "+settings.get("api_base"))

        try:
            self.api = api
            self.files = TempFiles()
        except Exception as e:
            logging.exception("ERROR: StableGimpfusionPlugin.__init__")

    def showMessage(self, text):
        gimp.pdb.gimp_message(text)

    def checkUpdate(self):
        try:
            gimp.get_data("update_checked")
            updateChecked = True
        except Exception as ex:
            updateChecked = False

        if updateChecked is False:
            try:
                response = urllib2.urlopen(PLUGIN_VERSION_URL)
                data = response.read()
                data = json.loads(data)
                gimp.set_data("update_checked", "1")

                if VERSION < int(data["version"]):
                    gimp.pdb.gimp_message(data["message"])
            except Exception as ex:
                ex = ex

    def getLayerAsBase64(self, layer):
        # store active_layer
        active_layer = layer.image.active_layer
        copy = Layer(layer).copy().insert()
        result = copy.toBase64()
        copy.remove()
        # restore active_layer
        gimp.pdb.gimp_image_set_active_layer(active_layer.image, active_layer)
        return result

    def getActiveLayerAsBase64(self):
        return self.getLayerAsBase64(self.image.active_layer)

    def getLayerMaskAsBase64(self, layer):
        non_empty, x1, y1, x2, y2 = gimp.pdb.gimp_selection_bounds(layer.image)
        if non_empty:
            # selection to base64

            # store active_layer
            active_layer = layer.image.active_layer

            # selection to file
            #disable=pdb.gimp_image_undo_disable(layer.image)
            tmp_layer = Layer.create(layer.image, "mask", layer.image.width, layer.image.height, gimpenums.RGBA_IMAGE, 100, gimpenums.NORMAL_MODE)
            tmp_layer.addSelectionAsMask().insert()

            result = tmp_layer.maskToBase64()
            tmp_layer.remove()
            #enable = pdb.gimp_image_undo_enable(layer.image)

            # restore active_layer
            gimp.pdb.gimp_image_set_active_layer(active_layer.image, active_layer)

            return result
        elif layer.mask:
            # mask to file
            tmp_layer = Layer(layer)
            return tmp_layer.maskToBase64()
        else:
            return ""

    def getActiveMaskAsBase64(self):
        return self.getLayerMaskAsBase64(self.image.active_layer)

    def getSelectionBounds(self):
        non_empty, x1, y1, x2, y2 = gimp.pdb.gimp_selection_bounds(self.image)
        if non_empty:
            return x1, y1, x2-x1, y2-y1
        return 0, 0, self.image.width, self.image.height

    def cleanup(self):
        self.files.removeAll()
        self.checkUpdate()

    def getControlNetParams(self, cn_layer):
        if cn_layer:
            layer = Layer(cn_layer)
            data = layer.loadData(CONTROLNET_DEFAULT_SETTINGS)
            # ControlNet image size need to be in multiples of 64
            layer64 = layer.copy().insert().resizeToMultipleOf(64)
            data.update({"input_image": layer64.toBase64()})
            if cn_layer.mask:
                data.update({"mask": layer64.maskToBase64()})
            layer64.remove()
            return data
        return None

    def imageToImage(self, *args):
        global settings
        resize_mode, prompt, negative_prompt, seed, batch_size, steps, mask_blur, width, height, cfg_scale, denoising_strength, sampler_index, cn1_enabled, cn1_layer, cn2_enabled, cn2_layer, cn_skip_annotator_layers = args
        image = self.image

        x, y, origWidth, origHeight = self.getSelectionBounds()

        data = {
            "resize_mode": resize_mode,
            "init_images": [self.getActiveLayerAsBase64()],

            "prompt": (prompt + " " + settings.get("prompt")).strip(),
            "negative_prompt": (negative_prompt + " " +  settings.get("negative_prompt")).strip(),
            "denoising_strength": float(denoising_strength),
            "steps": int(steps),
            "cfg_scale": float(cfg_scale),
            "width": roundToMultiple(width, 8),
            "height": roundToMultiple(height, 8),
            "sampler_index": SAMPLERS[sampler_index],
            "batch_size": min(MAX_BATCH_SIZE, max(1, batch_size)),
            "seed": seed or -1
        }

        try:
            gimp.pdb.gimp_progress_init("", None)
            gimp.pdb.gimp_progress_set_text(random.choice(GENERATION_MESSAGES))

            controlnet_units = []
            if cn1_enabled:
                controlnet_units.append(self.getControlNetParams(cn1_layer))
            if cn2_enabled:
                controlnet_units.append(self.getControlNetParams(cn2_layer))
            if len(controlnet_units) > 0:
                alwayson_scripts = {
                    "controlnet": {
                        "args": controlnet_units
                    }
                }
                data.update({"alwayson_scripts": alwayson_scripts})

            response = self.api.post("/sdapi/v1/img2img", data)

            ResponseLayers(image, response, {"skip_annotator_layers": cn_skip_annotator_layers}).resize(origWidth, origHeight)

        except Exception as ex:
            logging.exception("ERROR: StableGimpfusionPlugin.imageToImage")
            self.showMessage(repr(ex))
        finally:
            gimp.pdb.gimp_progress_end()
            self.cleanup()

    def inpainting(self, *args):
        global settings
        resize_mode, prompt, negative_prompt, seed, batch_size, steps, mask_blur, width, height, cfg_scale, denoising_strength, sampler_index, cn1_enabled, cn1_layer, cn2_enabled, cn2_layer, cn_skip_annotator_layers, invert_mask, inpaint_full_res = args
        image = self.image

        x, y, origWidth, origHeight = self.getSelectionBounds()

        init_images = [self.getActiveLayerAsBase64()]
        mask = self.getActiveMaskAsBase64()
        if mask == "":
            logging.exception("ERROR: StableGimpfusionPlugin.inpainting")
            raise Exception("Inpainting must use either a selection or layer mask")

        data = {
            "mask": mask,
            "inpaint_full_res": inpaint_full_res,
            "inpaint_full_res_padding": 10,
            "inpainting_mask_invert": 1 if invert_mask else 0,

            "resize_mode": resize_mode,
            "init_images": init_images,

            "prompt": (prompt + " " + settings.get("prompt")).strip(),
            "negative_prompt": (negative_prompt + " " +  settings.get("negative_prompt")).strip(),
            "denoising_strength": float(denoising_strength),
            "steps": int(steps),
            "cfg_scale": float(cfg_scale),
            "width": roundToMultiple(width, 8),
            "height": roundToMultiple(height, 8),
            "sampler_index": SAMPLERS[sampler_index],
            "batch_size": min(MAX_BATCH_SIZE, max(1, batch_size)),
            "seed": seed or -1
        }

        try:
            gimp.pdb.gimp_progress_init("", None)
            gimp.pdb.gimp_progress_set_text(random.choice(GENERATION_MESSAGES))

            controlnet_units = []
            if cn1_enabled:
                controlnet_units.append(self.getControlNetParams(cn1_layer))
            if cn2_enabled:
                controlnet_units.append(self.getControlNetParams(cn2_layer))

            if len(controlnet_units) > 0:
                alwayson_scripts = {
                    "controlnet": {
                        "args": controlnet_units
                    }
                }
                data.update({"alwayson_scripts": alwayson_scripts})

            response = self.api.post("/sdapi/v1/img2img", data)

            ResponseLayers(image, response, {"skip_annotator_layers": cn_skip_annotator_layers}).resize(self.image.width, self.image.height)

        except Exception as ex:
            logging.exception("ERROR: StableGimpfusionPlugin.inpainting")
            self.showMessage(repr(ex))
        finally:
            gimp.pdb.gimp_progress_end()
            self.cleanup()

    def textToImage(self, *args):
        global settings
        prompt, negative_prompt, seed, batch_size, steps, mask_blur, width, height, cfg_scale, denoising_strength, sampler_index, cn1_enabled, cn1_layer, cn2_enabled, cn2_layer, cn_skip_annotator_layers = args
        image = self.image

        x, y, origWidth, origHeight = self.getSelectionBounds()

        data = {
            "prompt": (prompt + " " + settings.get("prompt")).strip(),
            "negative_prompt": (negative_prompt + " " +  settings.get("negative_prompt")).strip(),
            "cfg_scale": float(cfg_scale),
            "denoising_strength": float(denoising_strength),
            "steps": int(steps),
            "width": roundToMultiple(width, 8),
            "height": roundToMultiple(height, 8),
            "sampler_index": SAMPLERS[sampler_index],
            "batch_size": min(MAX_BATCH_SIZE, max(1, batch_size)),
            "seed": seed or -1
        }

        try:
            gimp.pdb.gimp_progress_init("", None)
            gimp.pdb.gimp_progress_set_text(random.choice(GENERATION_MESSAGES))

            controlnet_units = []
            if cn1_enabled:
                controlnet_units.append(self.getControlNetParams(cn1_layer))
            if cn2_enabled:
                controlnet_units.append(self.getControlNetParams(cn2_layer))

            if len(controlnet_units) > 0:
                alwayson_scripts = {
                    "controlnet": {
                        "args": controlnet_units
                    }
                }
                data.update({"alwayson_scripts": alwayson_scripts})

            response = self.api.post("/sdapi/v1/txt2img", data)

            ResponseLayers(image, response, {"skip_annotator_layers": cn_skip_annotator_layers}).resize(origWidth, origHeight).translate((x, y)).addSelectionAsMask()

        except Exception as ex:
            logging.exception("ERROR: StableGimpfusionPlugin.textToImage")
            self.showMessage(repr(ex))
        finally:
            gimp.pdb.gimp_progress_end()
            self.cleanup()

    def showLayerInfo(self, *args):
        """ Show any layer info associated with the active layer """

        data = LayerData(self.image.active_layer).data
        gimp.pdb.gimp_message("This layer has the following data associated with it\n" + json.dumps(data, sort_keys=True, indent=4))


    def saveControlLayer(self, module, model, weight, resize_mode, lowvram, control_mode, guidance_start, guidance_end, guidance, processor_res, threshold_a, threshold_b):
        """ Take the form params and save them to the layer as gimp.Parasite """
        global settings
        cn_models = settings.get("cn_models", [])
        cn_settings = {
            "module": CONTROLNET_MODULES[module],
            "model": cn_models[model],
            "weight": weight,
            "resize_mode": CONTROLNET_RESIZE_MODES[resize_mode],
            "lowvram": lowvram,
            "control_mode": control_mode,
            "guidance_start": guidance_start,
            "guidance_end": guidance_end,
            "guidance": guidance,
            "processor_res": processor_res,
            "threshold_a": threshold_a,
            "threshold_b": threshold_b,
        }
        active_layer = self.image.active_layer
        cnlayer = Layer(active_layer)
        cnlayer.saveData(cn_settings)
        cnlayer.rename("ControlNet"+str(cnlayer.id))

    def config(self, prompt, negative_prompt, url):
        global settings
        settings.save({
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "api_base": url,
        })

    def changeModel(self, model):
        global settings
        if settings.get("model") != model:
            gimp.pdb.gimp_progress_init("", None)
            gimp.pdb.gimp_progress_set_text("Changing model...")
            try:
                self.api.post("/sdapi/v1/options", { "sd_model_checkpoint", model } )
                settings.set("sd_model_checkpoint", model)
            except Exception as e:
                logging.error(e)
            gimp.pdb.gimp_progress_end()


class TempFiles(object):
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = super(TempFiles, cls).__new__(cls)
        return cls.instance

    def __init__(self):
        self.files = []

    def get(self, filename):
        self.files.append(filename)
        return r"{}".format(os.path.join(tempfile.gettempdir(), filename))

    def removeAll(self):
        try:
            unique_list = (list(set(self.files)))
            for tmpfile in unique_list:
                if os.path.exists(tmpfile):
                    os.remove(tmpfile)
        except Exception as ex:
            ex = ex


class LayerData():
    def __init__(self, layer, defaults = {}):
        self.name = 'gimpfusion'
        self.layer = layer
        self.image = layer.image
        self.defaults = defaults
        self.had_parasite = False
        self.load()

    def load(self):
        parasite = self.layer.parasite_find(self.name)
        if not parasite:
            self.data = self.defaults.copy()
        else:
            self.had_parasite = True
            self.data = json.loads(parasite.data)
        self.data = deunicodeDict(self.data)
        return self.data

    def save(self, data):
        parasite = gimp.Parasite(self.name, gimpenums.PARASITE_PERSISTENT, deunicodeDict(json.dumps(data)))
        self.layer.parasite_attach(parasite)

class Layer():
    def __init__(self, layer = None):
        global layer_counter
        self.id = layer_counter 
        layer_counter = layer_counter + 1
        if layer is not None:
            self.layer = layer
            self.image = layer.image

    @staticmethod
    def create(image, name, width, height, image_type, opacity, mode):
        layer = gimp.Layer(image, name, width, height, image_type, opacity, mode)
        return Layer(layer)

    @staticmethod
    def fromBase64(img, base64Data):
        filepath = TempFiles().get("generated.png")
        imageFile = open(filepath, "wb+")
        imageFile.write(base64.b64decode(base64Data))
        imageFile.close()
        layer = gimp.pdb.gimp_file_load_layer(img, filepath)
        return Layer(layer)


    def rename(self, name):
        gimp.pdb.gimp_layer_set_name(self.layer, name)
        return self

    def saveData(self, data):
        LayerData(self.layer).save(data)
        return self

    def loadData(self, default_data):
        return LayerData(self.layer, default_data).data.copy()

    def copy(self):
        copy = gimp.pdb.gimp_layer_copy(self.layer, True)
        return Layer(copy)

    def scale(self, new_scale=1.0):
        if new_scale != 1.0:
            gimp.pdb.gimp_layer_scale(self.layer, int(new_scale * self.layer.width), int(new_scale * self.layer.height), False)
        return self

    def resize(self, width, height):
        logging.info("Resizing to %dx%d", width, height)
        gimp.pdb.gimp_layer_scale(self.layer, width, height, False)

    def resizeToMultipleOf(self, multiple):
        gimp.pdb.gimp_layer_scale(self.layer, roundToMultiple(self.layer.width, multiple), roundToMultiple(self.layer.height, multiple), False)
        return self

    def translate(self, offset=None):
        if offset is not None:
            gimp.pdb.gimp_layer_set_offsets(self.layer, offset[0], offset[1])
        return self

    def insert(self):
        gimp.pdb.gimp_image_insert_layer(self.image, self.layer, None, -1)
        return self

    def insertTo(self, image=None):
        image = image or self.image
        gimp.pdb.gimp_image_insert_layer(image, self.layer, None, -1)
        return self

    def addSelectionAsMask(self):
        mask = self.layer.create_mask(gimpenums.ADD_SELECTION_MASK)
        self.layer.add_mask(mask)
        return self

    def saveMaskAs(self, filepath):
        gimp.pdb.file_png_save(self.image, self.layer.mask, filepath, filepath, False, 9, True, True, True, True, True)
        return self

    def saveAs(self, filepath):
        gimp.pdb.file_png_save(self.image, self.layer, filepath, filepath, False, 9, True, True, True, True, True)
        return self

    def maskToBase64(self):
        filepath = TempFiles().get("mask"+str(self.id)+".png")
        self.saveMaskAs(filepath)
        file = open(filepath, "rb")
        return base64.b64encode(file.read())

    def toBase64(self):
        filepath = TempFiles().get("layer"+str(self.id)+".png")
        self.saveAs(filepath)
        file = open(filepath, "rb")
        return base64.b64encode(file.read())

    def remove(self):
        gimp.pdb.gimp_image_remove_layer(self.layer.image, self.layer)
        return self


class ResponseLayers():
    def __init__(self, img, response, options = {}):
        self.image = img
        color = gimp.pdb.gimp_context_get_foreground()
        gimp.pdb.gimp_context_set_foreground((0, 0, 0))

        layers = []
        try:
            info = json.loads(response["info"])
            infotexts = info["infotexts"]
            seeds = info["all_seeds"]
            index = 0
            logging.debug(infotexts)
            logging.debug(seeds)
            total_images = len(seeds)
            for image in response["images"]:
                if index < total_images:
                    layer_data = {"info": infotexts[index], "seed": seeds[index]}
                    layer = Layer.fromBase64(img, image).rename("Generated Layer "+str(seeds[index])).saveData(layer_data).insertTo(img)
                else:
                    # annotator layers
                    if "skip_annotator_layers" in options and not options["skip_annotator_layers"]:
                        layer = Layer.fromBase64(img, image).rename("Annotator Layer").insertTo(img)
                layers.append(layer.layer)
                index += 1
        except Exception as e:
            logging.exception("ResponseLayers")

        gimp.pdb.gimp_context_set_foreground(color)
        self.layers = layers

    def scale(self, new_scale=1.0):
        if new_scale != 1.0:
            for layer in self.layers:
                Layer(layer).scale(new_scale)
        return self

    def resize(self, width, height):
        for layer in self.layers:
            Layer(layer).resize(width, height)
        return self

    def translate(self, offset=None):
        if offset is not None:
            for layer in self.layers:
                Layer(layer).translate(offset)
        return self

    def insertTo(self, image=None):
        image = image or self.image
        for layer in self.layers:
            Layer(layer).insertTo(image)
        return self

    def addSelectionAsMask(self):
        non_empty, x1, y1, x2, y2 = gimp.pdb.gimp_selection_bounds(self.image)
        if not non_empty:
            return
        if (x1 == 0) and (y1 == 0) and (x2 - x1 == self.image.width) and (y2 - y1 == self.image.height):
            return
        for layer in self.layers:
            Layer(layer).addSelectionAsMask()
        return self

def handleConfig(image, drawable, *args):
    print((image, drawable, args))
    StableGimpfusionPlugin(image).config(*args)

def handleChangeModel(image, drawable, *args):
    logging.info(image, drawable, *args)
    StableGimpfusionPlugin(image).changeModel(*args)

def handleImageToImage(image, drawable, *args):
    StableGimpfusionPlugin(image).imageToImage(*args)

def handleInpainting(image, drawable, *args):
    StableGimpfusionPlugin(image).inpainting(*args)

def handleTextToImage(image, drawable, *args):
    StableGimpfusionPlugin(image).textToImage(*args)

def handleControlNetLayerConfig(image, drawable, *args):
    StableGimpfusionPlugin(image).saveControlLayer(*args)

def handleShowLayerInfo(image, drawable, *args):
    StableGimpfusionPlugin(image).showLayerInfo(*args)

def handleImageToImageFromLayersContext(image, drawable, *args):
    StableGimpfusionPlugin(image).imageToImage(*args)

def handleInpaintingFromLayersContext(image, drawable, *args):
    StableGimpfusionPlugin(image).inpainting(*args)

def handleTextToImageFromLayersContext(image, drawable, *args):
    StableGimpfusionPlugin(image).textToImage(*args)

def handleControlNetLayerConfigFromLayersContext(image, drawable, *args):
    StableGimpfusionPlugin(image).saveControlLayer(*args)

def handleShowLayerInfoContext(image, drawable, *args):
    StableGimpfusionPlugin(image).showLayerInfo(*args)

def init_plugin():
    global settings, api, sd_model, models, is_server_running

    settings = MyShelf(STABLE_GIMPFUSION_DEFAULT_SETTINGS)
    api = ApiClient(settings.get("api_base"))
    fetch_stablediffusion_options()
    models = settings.get("models", [])
    sd_model_checkpoint = settings.get("sd_model_checkpoint")
    is_server_running = settings.get("is_server_running")
    logging.info(settings)

    PLUGIN_FIELDS_IMAGE = [
            (gimpfu.PF_IMAGE, "image", "Image", None),
            (gimpfu.PF_DRAWABLE, "drawable", "Drawable", None),
            ]

    PLUGIN_FIELDS_LAYERS = [
            (gimpfu.PF_IMAGE, "image", "Image", None),
            (gimpfu.PF_LAYER, "layer", "Layer", None),
            ]

    PLUGIN_FIELDS_COMMON = [
            (gimpfu.PF_TEXT, "prompt", "Prompt", settings.get("prompt")),
            (gimpfu.PF_TEXT, "negative_prompt", "Negative Prompt", settings.get("negative_prompt")),
            (gimpfu.PF_INT32, "seed", "Seed", settings.get("seed")),
            (gimpfu.PF_SLIDER, "batch_size", "Batch count", settings.get("batch_size"), (1, 20, 1.0)),
            (gimpfu.PF_SLIDER, "steps", "Steps", settings.get("steps"), (10, 150, 1.0)),
            (gimpfu.PF_SLIDER, "mask_blur", "Mask Blur", settings.get("mask_blur"), (1, 10, 1.0)),
            (gimpfu.PF_SLIDER, "width", "Width", settings.get("width"), (64, 2048, 8)),
            (gimpfu.PF_SLIDER, "height", "Height", settings.get("height"), (64, 2048, 8)),
            (gimpfu.PF_SLIDER, "cfg_scale", "CFG Scale", settings.get("cfg_scale"), (0, 20, 0.5)),
            (gimpfu.PF_SLIDER, "denoising_strength", "Denoising Strength", settings.get("denoising_strength"), (0.0, 1.0, 0.01)),
            (gimpfu.PF_OPTION, "sampler_index", "Sampler", SAMPLERS.index(settings.get("sampler_name")), SAMPLERS),
            ]

    PLUGIN_FIELDS_CONTROLNET_OPTIONS = [
            (gimpfu.PF_TOGGLE, "cn1_enabled", "Enable ControlNet 1", False),
            (gimpfu.PF_LAYER, "cn1_layer", "ControlNet 1 Layer", None),
            (gimpfu.PF_TOGGLE, "cn2_enabled", "Enable ControlNet 2", False),
            (gimpfu.PF_LAYER, "cn2_layer", "ControlNet 2 Layer", None),
            (gimpfu.PF_TOGGLE, "cn_skip_annotator_layers", "Skip annotator layers", True),
            ]

    PLUGIN_FIELDS_CONFIG = [
        (gimpfu.PF_STRING, "prompt", "Prompt Suffix", settings.get("prompt")),
        (gimpfu.PF_STRING, "negative_prompt", "Negative Prompt Suffix", settings.get("negative_prompt")),
        (gimpfu.PF_STRING, "api_base", "Backend API URL base", settings.get("api_base")),
        ]

    logging.info(models)
    if sd_model_checkpoint is not None:
        PLUGIN_FIELDS_CHECKPOINT = [
            (gimpfu.PF_OPTION, "model", "Model", models.index(sd_model_checkpoint), models)
            ]
    else:
        PLUGIN_FIELDS_CHECKPOINT = []


    PLUGIN_FIELDS_RESIZE_MODE = [(gimpfu.PF_OPTION, "resize_mode", "Resize Mode", 0, tuple(RESIZE_MODES.keys()))]
    PLUGIN_FIELDS_TXT2IMG = [] + PLUGIN_FIELDS_COMMON + PLUGIN_FIELDS_CONTROLNET_OPTIONS
    PLUGIN_FIELDS_IMG2IMG = [] + PLUGIN_FIELDS_RESIZE_MODE + PLUGIN_FIELDS_TXT2IMG
    PLUGIN_FIELDS_INPAINTING = [
        (gimpfu.PF_TOGGLE, "invert_mask", "Invert Mask", False),
        (gimpfu.PF_TOGGLE, "inpaint_full_res", "Inpaint Whole Picture", True),
        ]


    PLUGIN_FIELDS_CONTROLNET = [] + [
            (gimpfu.PF_OPTION, "module", "Module", 0, CONTROLNET_MODULES),
            (gimpfu.PF_OPTION, "model", "Model", 0, settings.get("cn_models", ["none"])),
            (gimpfu.PF_SLIDER, "weight",  "Weight", 1, (0, 2, 0.05)),
            (gimpfu.PF_OPTION, "resize_mode", "Resize Mode", 1, CONTROLNET_RESIZE_MODES),
            (gimpfu.PF_BOOL, "lowvram", "Low VRAM", False),
            (gimpfu.PF_OPTION, "control_mode", "Control Mode", 0, tuple(CONTROL_MODES.keys())),
            (gimpfu.PF_SLIDER, "guidance_start",  "Guidance Start (T)", 0, (0, 1, 0.01)),
            (gimpfu.PF_SLIDER, "guidance_end",  "Guidance End (T)", 1, (0, 1, 0.01)),
            (gimpfu.PF_SLIDER, "guidance",  "Guidance", 1, (0, 1, 0.01)),
            (gimpfu.PF_SLIDER, "processor_res",  "Processor Resolution", 512, (64, 2048, 1)),
            (gimpfu.PF_SLIDER, "threshold_a",  "Threshold A", 64, (100, 2048, 1)),
            (gimpfu.PF_SLIDER, "threshold_b",  "Threshold B", 64, (200, 2048, 1)),
            ]

    gimpfu.register(
            "stable-gimpfusion-config",
            "This is where you configure params that are shared between all API requests",
            "Gimp Client for the StableDiffusion Automatic1111 API",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Global",
            "*",      # Alternately use RGB, RGB*, GRAY*, INDEXED etc.
            [] + PLUGIN_FIELDS_IMAGE + PLUGIN_FIELDS_CONFIG,
            [],
            handleConfig, menu="<Image>/GimpFusion/Config",
            )

    gimpfu.register(
            "stable-gimpfusion-config-model",
            "Change the Checkpoint Model",
            "Change the Checkpoint Model",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Change Model",
            "*",
            [] + PLUGIN_FIELDS_IMAGE + PLUGIN_FIELDS_CHECKPOINT,
            [],
            handleChangeModel, menu="<Image>/GimpFusion/Config"
            )

    gimpfu.register(
            "stable-gimpfusion-txt2img",
            "Text to image",
            "Text to image",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Text to image",
            "*",
            []+ PLUGIN_FIELDS_IMAGE + PLUGIN_FIELDS_TXT2IMG,
            [],
            handleTextToImage, menu="<Image>/GimpFusion"
            )


    gimpfu.register(
            "stable-gimpfusion-txt2img-context",
            "Text to image",
            "Text to image",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Text to image",
            "*",
            [] + PLUGIN_FIELDS_LAYERS + PLUGIN_FIELDS_TXT2IMG,
            [],
            handleTextToImageFromLayersContext, menu="<Layers>/GimpFusion"
            )


    gimpfu.register(
            "stable-gimpfusion-img2img",
            "Image to image",
            "Image to image",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Image to image",
            "*",
            []+ PLUGIN_FIELDS_IMAGE + PLUGIN_FIELDS_IMG2IMG,
            [],
            handleImageToImage, menu="<Image>/GimpFusion"
            )

    gimpfu.register(
            "stable-gimpfusion-img2img-context",
            "Image to image",
            "Image to image",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Image to image",
            "*",
            [] + PLUGIN_FIELDS_LAYERS + PLUGIN_FIELDS_IMG2IMG,
            [],
            handleImageToImageFromLayersContext, menu="<Layers>/GimpFusion"
            )

    gimpfu.register(
            "stable-gimpfusion-inpainting",
            "Inpainting",
            "Inpainting",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Inpainting",
            "*",
            []+ PLUGIN_FIELDS_IMAGE + PLUGIN_FIELDS_IMG2IMG + PLUGIN_FIELDS_INPAINTING,
            [],
            handleInpainting, menu="<Image>/GimpFusion"
            )

    gimpfu.register(
            "stable-gimpfusion-inpainting-context",
            "Inpainting",
            "Inpainting",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Inpainting",
            "*",
            [] + PLUGIN_FIELDS_LAYERS + PLUGIN_FIELDS_IMG2IMG,
            [],
            handleInpaintingFromLayersContext, menu="<Layers>/GimpFusion"
            )

    gimpfu.register(
            "stable-gimpfusion-config-controlnet-layer",
            "Convert current layer to ControlNet layer or edit ControlNet Layer's options",
            "ControlNet Layer",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Active layer as ControlNet",
            "*",
            []+ PLUGIN_FIELDS_IMAGE + PLUGIN_FIELDS_CONTROLNET,
            [],
            handleControlNetLayerConfig, menu="<Image>/GimpFusion"
            )

    gimpfu.register(
            "stable-gimpfusion-config-controlnet-layer-context",
            "Convert current layer to ControlNet layer or edit ControlNet Layer's options",
            "ControlNet Layer",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Use as ControlNet",
            "*",
            [] + PLUGIN_FIELDS_LAYERS + PLUGIN_FIELDS_CONTROLNET,
            [],
            handleControlNetLayerConfigFromLayersContext, menu="<Layers>/GimpFusion"
            )

    gimpfu.register(
            "stable-gimpfusion-layer-info",
            "Show stable gimpfusion info associated with this layer",
            "Layer Info",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Layer Info",
            "*",
            [] + PLUGIN_FIELDS_IMAGE,
            [],
            handleShowLayerInfo, menu="<Image>/GimpFusion/Config"
            )

    gimpfu.register(
            "stable-gimpfusion-layer-info-context",
            "Show stable gimpfusion info associated with this layer",
            "Layer Info",
            "ArtBIT",
            "ArtBIT",
            "2023",
            "Layer Info",
            "*",
            [] + PLUGIN_FIELDS_LAYERS,
            [],
            handleShowLayerInfoContext, menu="<Layers>/GimpFusion"
            )

init_plugin()
gimpfu.main()

