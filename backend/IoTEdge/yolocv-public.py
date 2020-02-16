# This code is written at BigVision LLC. It is based on the OpenCV project. It is subject to the license terms in the LICENSE file found in this distribution and at http://opencv.org/license.html

# Usage example:  python3 object_detection_yolo.py --video=run.mp4
#                 python3 object_detection_yolo.py --image=bird.jpg
import cv2 as cv
import iotc
from iotc import IOTConnectType, IOTLogLevel

import argparse
import requests
import sys
import numpy as np
from urllib.request import urlopen
import os
import datetime
from random import randint
import time
from iothub_client import IoTHubClient, IoTHubTransportProvider, IoTHubMessage


#iot central initalize 
deviceId = "your device id on iot central"
scopeId = "iot central scope id"
mkey = "SAS Key on IoT Central"

iotc = iotc.Device(scopeId, mkey, deviceId, IOTConnectType.IOTC_CONNECT_SYMM_KEY)
iotc.setLogLevel(IOTLogLevel.IOTC_LOGGING_API_ONLY)

gCanSend = False
gCounter = 0
sttenabled = False
alertcnt = 0

def onconnect(info):
  global gCanSend
  print("- [onconnect] => status:" + str(info.getStatusCode()))
  if info.getStatusCode() == 0:
     if iotc.isConnected():
       gCanSend = True

def onmessagesent(info):
  print("\t- [onmessagesent] => " + str(info.getPayload()))

def oncommand(info):
  print("- [oncommand] => " + info.getTag() + " => " + str(info.getPayload()))

def onsettingsupdated(info):
  print("- [onsettingsupdated] => " + info.getTag() + " => " + info.getPayload())
  #d = json.loads(info.getPayload())
  

iotc.on("ConnectionStatus", onconnect)
iotc.on("MessageSent", onmessagesent)
iotc.on("Command", oncommand)
iotc.on("SettingsUpdated", onsettingsupdated)
iotc.connect()

# Initialize the parameters
confThreshold = 0.5  #Confidence threshold
nmsThreshold = 0.4   #Non-maximum suppression threshold置信度阈值
inpWidth = 320       #Width of network's input image，改为320*320更快
inpHeight = 320      #Height of network's input image，改为608*608更准
IMAGE_PROCESSING_ENDPOINT = 'http://localhost:8081/classify/helmets'
resetcnt=0

parser = argparse.ArgumentParser(description='Object Detection using YOLO in OPENCV')
parser.add_argument('--image', help='Path to image file.')
parser.add_argument('--video', help='Path to video file.')
args = parser.parse_args()

# Load names of classes
classesFile = "YOLO\\coco.names"
classes = None
with open(classesFile, 'rt') as f:
    classes = f.read().rstrip('\n').split('\n')

# Give the configuration and weight files for the model and load the network using them.
modelConfiguration = "YOLO\\yolov3-tiny.cfg";
modelWeights = "YOLO\\yolov3-tiny.weights";

net = cv.dnn.readNetFromDarknet(modelConfiguration, modelWeights)
net.setPreferableBackend(cv.dnn.DNN_BACKEND_OPENCV)
net.setPreferableTarget(cv.dnn.DNN_TARGET_CPU) #可切换到GPU,cv.dnn.DNN_TARGET_OPENCL，
# 只支持Intel的GPU,没有则自动切换到cpu

def send_confirmation_callback(message, result, user_context):
        print("Confirmation received for message with result = %s" % (result))
        
def sendFrameForProcessing(frame):
    # def do_req():
    #     return requests.post(self.imageProcessingEndpoint, headers = headers, params = "", data = frame)    
    # t = time.time()
    # print("Send a request at",t-start_time,"seconds.")
    #session = FuturesSession()
    headers = {'Content-Type': 'application/octet-stream'}
    response = requests.post(IMAGE_PROCESSING_ENDPOINT, headers = headers, params = "", data = frame)
    #response = await loop.run_in_executor(None,do_req)
    # t = time.time()
    # print("Receive a response at",t-start_time,"seconds.")
    # print(response)
    # first request is started in background
    #future_one = session.post(self.imageProcessingEndpoint, headers = headers, params = "", data = frame)
    #response = future_one.result()
    try:
        print("Response from external processing service: (" + str(response.status_code) + ") " + json.dumps(response.json()))
    except Exception:
        print("Response from external processing service (status code): " + str(response.status_code))
    try:
        return response.json()
    except:
        print('error')
        return ""

# Get the names of the output layers
def getOutputsNames(net):
    # Get the names of all the layers in the network
    layersNames = net.getLayerNames()
    # Get the names of the output layers, i.e. the layers with unconnected outputs
    return [layersNames[i[0] - 1] for i in net.getUnconnectedOutLayers()]

# Draw the predicted bounding box
def drawPred(classId, conf, addt, fc, left, top, right, bottom):
    # Draw a bounding box.
    cv.rectangle(frame, (left, top), (right, bottom), fc , 3) #(255, 178, 50)

    label = '%.2f' % conf

    # Get the label for the class name and its confidence
    if classes:
        assert(classId < len(classes))
        #print(classId)
        label = '%s-%s:%s' % (classes[classId],addt, label)
        print(classes[classId])
    
    #Display the label at the top of the bounding box
    labelSize, baseLine = cv.getTextSize(label, cv.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    top = max(top, labelSize[1])
    cv.rectangle(frame, (left, top - round(1.5*labelSize[1])), (left + round(1.5*labelSize[0]), top + baseLine), fc, cv.FILLED)
    cv.putText(frame, label, (left, top), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,0), 1)

# Remove the bounding boxes with low confidence using non-maxima suppression
def postprocess(frame, outs):
    frameHeight = frame.shape[0]
    frameWidth = frame.shape[1]

    classIds = []
    confidences = []
    boxes = []
    additionaltext = []
    framecolor = []
    # Scan through all the bounding boxes output from the network and keep only the
    # ones with high confidence scores. Assign the box's class label as the class with the highest score.
    classIds = []
    confidences = []
    boxes = []
    additionaltext = []
    framecolor = []
    masktext =""

    global resetcnt
    global alertcnt
    for out in outs:
        for detection in out:
            scores = detection[5:]
            classId = np.argmax(scores)
            confidence = scores[classId]
            if confidence > confThreshold:
                center_x = int(detection[0] * frameWidth)
                center_y = int(detection[1] * frameHeight)
                width = int(detection[2] * frameWidth)
                height = int(detection[3] * frameHeight)
                left = int(center_x - width / 2)
                top = int(center_y - height / 2)
                classIds.append(classId)
                confidences.append(float(confidence))
                boxes.append([left, top, width, height])

                #framecolor = (255, 0, 0)
                #additionaltext = ''
                #personIme = image[x1:x2, y1:y2]
                #print(personIme)
                try:
                    encodedFrame = cv.imencode(".jpg", frame )[1].tostring()
                    # Send over HTTP for processing
                    response = sendFrameForProcessing( encodedFrame )  
                    print(response)                  
                    if response != '':
                    #     if response['confidence'] > 0.50 and str( response['class'] ) == 'Facemas':#ConstructionHelmet
                    #         #framecolor = (0, 255, 0)
                    #         framecolor.append((0, 255, 0))
                    #         masktext = str.format('[Mask, %.2f]' % response['confidence'])
                    #         additionaltext.append(masktext)
                    #         #resetcnt=11
                    #     else:
                    #         #framecolor = (0, 0, 255)
                    #         masktext = str.format('[No Mask, %.2f]' % response['confidence'])
                    #         framecolor.append((0, 0, 255))
                    #         additionaltext.append(masktext)
                    #         resetcnt = resetcnt + 1
                        if response['confidence'] > 0.50 and str( response['class'] ) == 'Facemask':#ConstructionHelmet
                            #framecolor = (0, 255, 0)
                            framecolor.append((0, 255, 0))
                            masktext = str.format('[Mask, %.2f]' % response['confidence'])
                            additionaltext.append(masktext)
                            #msg = Message('{"mask":"Yes","alertcnt":'+str(alertcnt)+',"level":' + str(response['confidence']*100)+'}')
                            iotc.sendTelemetry('{"mask":"Yes","alertcnt":'+str(alertcnt)+',"level":' + str(response['confidence']*100)+'}')
                            #device_client.send_message(msg)
                            #msg = Message("test wind speed " + str(i))
                            #resetcnt=11
                        elif response['confidence'] > 0.30 and str( response['class'] ) == 'Nomas':
                            #framecolor = (0, 0, 255)
                            masktext = str.format('[No Mask, %.2f]' % response['confidence'])
                            framecolor.append((0, 0, 255))
                            additionaltext.append(masktext)
                            msg = '{"mask":"No","alertcnt":'+str(alertcnt)+',"level":' + str(response['confidence']*100)+'}'
                            resetcnt = resetcnt + 1 
                        else :
                            print(resetcnt)
                            framecolor.append((255, 0, 0))
                            additionaltext.append("")      
                        #print(resetcnt)
                        
                        print(resetcnt)
                        iotc.sendProperty('{"masktext":"'+masktext+'"}')
                        #message = IoTHubMessage(masktext)
                        if(resetcnt>3):
                            #client.send_event_async(message, send_confirmation_callback, None)
                            iotc.sendTelemetry(msg)
                            iotc.sendState('{ "status": "WARNING"}')
                            # iotc.sendTelemetry("{ \
                            #     \"temp\": " + str(randint(20, 45)) + ", \
                            #     \"accelerometerX\": " + str(randint(2, 15)) + ", \
                            #     \"accelerometerY\": " + str(randint(3, 9)) + ", \
                            #     \"accelerometerZ\": " + str(randint(1, 4)) + "}")
                            print("Message transmitted to IoT Central")
                            resetcnt=0
                            alertcnt = alertcnt + 1       

                except Exception as e:
                    print('Error frmae processing: ' + str(e))


    # Perform non maximum suppression to eliminate redundant overlapping boxes with
    # lower confidences.
    indices = cv.dnn.NMSBoxes(boxes, confidences, confThreshold, nmsThreshold)
    for i in indices:
        i = i[0]
        box = boxes[i]
        left = box[0]
        top = box[1]
        width = box[2]
        height = box[3]
        drawPred(classIds[i], confidences[i],additionaltext[i], framecolor[i] ,left, top, left + width, top + height)

# Process inputs
winName = 'Deep learning object detection in OpenCV'
#cv.namedWindow(winName, cv.WINDOW_NORMAL)

outputFile = "yolo_out_py.avi"
# Webcam input
url="http://192.168.43.138:81/stream"
CAMERA_BUFFRER_SIZE=4096
stream=urlopen(url)
bts=b''

# Get the video writer initialized to save the output video
#if (not args.image):
#   vid_writer = cv.VideoWriter(outputFile, cv.VideoWriter_fourcc('M','J','P','G'), 30, (round(cap.get(cv.CAP_PROP_FRAME_WIDTH)),round(cap.get(cv.CAP_PROP_FRAME_HEIGHT))))

while cv.waitKey(1) < 0:
    bts+=stream.read(CAMERA_BUFFRER_SIZE)
    jpghead=bts.find(b'\xff\xd8')
    jpgend=bts.find(b'\xff\xd9')
    if jpghead>-1 and jpgend>-1:
        jpg=bts[jpghead:jpgend+2]
        bts=bts[jpgend+2:]
        #print(jpg)
        if jpg != b'' :
            img=cv.imdecode(np.frombuffer(jpg,dtype=np.uint8),cv.IMREAD_UNCHANGED)
            v=cv.flip(img,0)
            h=cv.flip(img,1)
            p=cv.flip(img,-1)        
            frame=p
            h,w=frame.shape[:2]
            frame=cv.resize(frame,(416,416))
            blob = cv.dnn.blobFromImage(frame, 1/255, (inpWidth, inpHeight), [0,0,0], 1, crop=False)
            net.setInput(blob)
            # Runs the forward pass to get output of the output layers
            outs = net.forward(getOutputsNames(net))
            # Remove the bounding boxes with low confidence
            postprocess(frame, outs)


            # Put efficiency information. The function getPerfProfile returns the overall time for inference(t) and the timings for each of the layers(in layersTimes)
            t, _ = net.getPerfProfile()
            label = 'Inference time: %.2f ms' % (t * 1000.0 / cv.getTickFrequency())
            cv.putText(frame, label, (0, 15), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255))
            cv.imshow(winName, frame)