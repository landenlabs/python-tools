#!/usr/bin/python3
import os
from stat import * # ST_SIZE etc
import sys
import time

import subprocess
from subprocess import Popen
import functools
import threading
import glob
import shutil
import re
import io
# import queue

import base64   ## uuencode/decode

# Ansii escape sequence for color on OSX/Linux
def prRed(prt): print(("\033[91m {}\033[00m" .format(prt)))
def prGreen(prt): print(("\033[92m {}\033[00m" .format(prt)))
def prYellow(prt): print(("\033[93m {}\033[00m" .format(prt)))
def prLightPurple(prt): print(("\033[94m {}\033[00m" .format(prt)))
def prPurple(prt): print(("\033[95m {}\033[00m" .format(prt)))
def prCyan(prt): print(("\033[96m {}\033[00m" .format(prt)))
def prLightGray(prt): print(("\033[97m {}\033[00m" .format(prt)))
def prBlack(prt): print(("\033[98m {}\033[00m" .format(prt)))

# ---------------------------------------------------------------------------------------
#------------------ Stbus for color -----------------------------------------------------

def printRed(msg):
  prRed(msg)

def printYellow(msg):
  prYellow(msg)

def printWhite(msg):
  print(msg)

def printCyan(msg):
  prCyan(msg)

# ---------------------------------------------------------------------------------------

appbuildVersion = "adb-tool v2.01 (Feb)"
buildCommand = 'install'
buildType = 'Release'
buildOpt = ' ';
flavorName = 'none'
specialCommand = 'none'
flavorNames = []

apkDir = os.path.join("build", "outputs", "apk");

def showHelp():
    global appbuildVersion
    printYellow(appbuildVersion)
    print("")
    printWhite("TWC adb tool")
    printWhite("=======================================")
    print("")
    printYellow("Usage:")
    print("   adb-tool.py  <command> <buildType> <flavor> [qc|noqc]")
    print("")
    printYellow("Commands:")
    print("      trace        Show crash traces from attached device")
    print("      list         List built and installed packages")
    print("")
    print("      encode       Base64 encode input")
    print("      decode       Base64 decode input")
    print("")
    printYellow("Notes:")
    print("   Install and Release are the defaults, so only flavor is required")
    print("   Argument order is not important")
    print("   <command> and  <buildType> ignores case")
    print("")
    printYellow("Examples:")
    print("   Show recent crash traces from attached device")
    printCyan("       adb-tool.py  trace")
    print("")
    print("   List built APK and if device connected, installed APK ")
    printCyan("       adb-tool.py list ")
    print("   Install built APK(s) ")
    print("       The apk name can be abbreviated, will select newest match")
    printCyan("       adb-tool.py install wx2 ")
    printCyan("       adb-tool.py install wx2 stress ")
    print("")
    print("")
    sys.exit(1)


# Store argument in appropriate global variable
def parseArg(arg):
    global buildCommand, buildType, buildOpt, flavorName, specialCommand

    argLwr = arg.lower()
    if  (argLwr == 'trace') or (argLwr == 'list') :
        specialCommand = argLwr;
    elif (argLwr == 'encode') or (argLwr == 'decode'):
        specialCommand = argLwr;
    elif ('help' in argLwr) or ('?' in arg):
        showHelp()
    else:
        flavorName = arg            #  flavorName = os.path.splitext(os.path.basename(arg))[0]
        flavorNames.append(arg)

# Verify target path exists
def verifyFlavor():
    global flavorName

    if flavorName == 'none':
        printRed("[ERROR] - Missing flavor to build")
        showHelp()
        sys.exit(2);

    flavorName = os.path.splitext(os.path.basename(flavorName))[0]
    targetPath = os.path.join("TargetResources", flavorName, flavorName + ".properties")
    if not os.path.exists(targetPath):
        printRed("\a\n[ERROR] - " + targetPath + " does not exist\n\a")
        sys.exit(3);

    # Get target filename in correct Case.
    ## osNames = glob.glob(os.path.join("TargetResources", flavorName) + "*")
    ## osName = osNames[0]
    ## flavorName = os.path.splitext(os.path.basename(osName))[0] 
    for osName in os.listdir("TargetResources"):
        if osName.lower() == flavorName.lower():
           break;
    ## [osName for osName in os.listdir("TargetResources")
    ##    if osName.lower() != flavorName.lower()]
    if osName.lower() != flavorName.lower():
        printRed("[ERROR] - Unknown flavor " + flavorName + ", check TargetResources directory")
        sys.exit(2);
    flavorName = osName;


def doListCommand():
    global apkDir
    dir = apkDir
    printYellow("--- List of built APK's " + dir + " ----")
    for filename in glob.iglob(apkDir + '**/**', recursive=True):
        if  ('.apk' in filename):
            st = os.stat(filename)
            if (S_ISREG(st.st_mode)):
                print(("%8d  %s %s" % (st[ST_SIZE], time.asctime(time.localtime(st[ST_MTIME])), filename)));

    printYellow ("---- List of installed packages ----")
    pipe1 = os.popen('adb shell pm list packages -3')
    list1 = pipe1.readlines()

    for line1 in list1:
        if ("android.weather" in line1 or "mylocaltv" in line1 or "youngmedia" in line1 or "twc" in line1):
            printCyan(line1.strip());
            if ":" in line1:
                parts = [i for i in line1.split(":") if i != ""]
                dumpCmd = 'adb shell dumpsys package ' + parts[1].strip()
                pipe2 = os.popen(dumpCmd)
                
                for line2 in pipe2.readlines():
                    # print(line2)
                    line2 = line2.strip()
                    # print(" ...." + line2)
                    if ('version' in line2) or ('pkgFlags' in line2) or ('Time' in line2):
                        print(("    " + line2))


def doTraceCommand():
    
    show = 0
    traceCnt = 0;
    procId = '_none_'

    proc = Popen(['adb', 'logcat', '-d'],
                 stdout=subprocess.PIPE,
                 stderr=subprocess.PIPE,
                 text=True,
                 encoding='utf-8',
                 errors='ignore',  # This is the key part
                 universal_newlines=True)
    for line in iter(proc.stdout.readlines()):
        line = line.strip()
        # print(line)
        if ('FATAL EXCEPTION' in line):
            printYellow("---- Show Traces ----")
            traceCnt = traceCnt + 1
            show = 1
            parts = [i for i in line.split("FATAL") if i != ""]
            parts = [i for i in parts[0].split("E") if i != ""]
            procId = parts[0]
            if (len(parts) > 1):
                procId = parts[1]
            print((line.strip()));
        elif (show > 0) and (procId in line):
            parts = [i for i in line.strip().split(procId) if i != ""]
            print((parts[1]));
            show = show + 1
        elif (show > 0):
            printYellow("---- End Trace ----\n")
            show = 0
            procId = '_none_'
    if (traceCnt == 0):
        printYellow("---- Show Error logs with 'java' ----")
        pipe = os.popen('adb logcat -d "*:E"')
        for line in pipe.readlines():
            if ('java' in line):
                print((line), end=' ')

def doCleanCommand():
    global flavorName
    if flavorName == 'none':
        cmd = "gradlew clean"
        printYellow("Executing " + cmd)
        os.system(os.getcwd() + "/" + cmd)
    else:
        flavorName = os.path.splitext(os.path.basename(flavorName))[0]
        buildDir = "build"
        for dirPath, subdirList, fileList in os.walk(buildDir):
            for dname in subdirList:
                if dname == flavorName:
                    subDirPath = os.path.join(dirPath, dname)
                    print(('\t%s' % subDirPath))
                    shutil.rmtree(subDirPath)


def doInstallCommand():
    # install arg using ADB
    
    #
    #  aapt dump badging build/outputs//apk/WxApp-WSICarousel-release.apk 
    #     get packagename
    #  adb pm uninstall -k packagename
    #  adb install -r apk.
    #
    global apkDir
    dir = apkDir
    print("Install " + flavorName)

    printYellow("--- List of built APK's " + dir + " ----")
    # for filename in os.listdir(dir):

    # pprint([(x[0], time.ctime(x[1].st_ctime)) for x in
    #        sorted([(fn, os.stat(os.path.join(dir, fn))) for fn in os.listdir(dir)], key=lambda x: -x[1].st_ctime)])

    for fileNameAndSize in sorted([(fn, os.stat(os.path.join(dir, fn))) for fn in os.listdir(dir)], key=lambda x: -x[1].st_ctime):
        filename = fileNameAndSize[0]
        apkPath = os.path.join(dir, filename)
        if 'unaligned' in filename:
            os.remove(apkPath)
        elif flavorName.lower() in filename.lower():
            st = os.stat(apkPath)
            print(("%30s  %8d  %s" % (filename, st[ST_SIZE], time.asctime(time.localtime(st[ST_MTIME])))));
            proc = subprocess.Popen("adb devices", stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            (out, err) = proc.communicate()
            # out = re.sub("\\n", "\n", out)
            print(out.decode('ISO-8859-1'))
            cmd = "adb -d install -r -t -d " + apkPath
            print(("Executing " + cmd))
            # os.system(cmd)
            # proc = subprocess.Popen(["adb", "-d", "install", "-r", "-t", apkPath], stdout=subprocess.PIPE, shell=True)
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            (out, err) = proc.communicate()
            name = filename.replace('.apk','').replace('-debug','').replace('-release','').replace('WxApp-','')
            out = re.sub(".*Install", "Install", out.decode('ISO-8859-1'))
            print((out + " on " + name))
            cmd = "say -v karen '" + out + " on " + name + "'"
            # os.system(cmd)
            subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            return


def doEncodeCommand():
    # base64 encode input stream
    for inLine in sys.stdin:
        inAsBytes = inLine.rstrip().encode('ascii')
        outEncodedBytes = base64.b64encode(inAsBytes)
        outEncoded = outEncodedBytes.decode('ascii')
        print(outEncoded)
    return
    
def doDecodeCommand():
    # base64 decode input stream
    for inLine in sys.stdin:
        inAsBytes = inLine.rstrip().encode('ascii')
        outDecodedBytes = base64.b64decode(inAsBytes)
        outDecoded = outDecodedBytes.decode('ascii')
        print(outDecoded)
    return
    
    
def doSpecialCommand():
    global flavorName
    
    if specialCommand == 'clean':
        doCleanCommand()
    elif specialCommand == 'list':
        doListCommand()
    elif specialCommand == 'trace':
        doTraceCommand()
    elif specialCommand == 'encode':
        doEncodeCommand()
    elif specialCommand == 'decode':
        doDecodeCommand()
    elif specialCommand == 'install':
        for name in flavorNames:
            flavorName = name
            doInstallCommand()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        showHelp()
    else:
        for idx in range(1, len(sys.argv)):
            parseArg(sys.argv[idx])

    ## if len(sys.argv) > 2:
    ##    parseArg(sys.argv[2])

    if specialCommand != 'none':
        doSpecialCommand()
    else:
        for name in flavorNames:
            flavorName = name
            verifyFlavor()

            ## Remove old APK before build
            cmd = "rm -rf build/outputs/apk/*" + flavorName + "*"
            print(("Executing " + cmd))
            os.system(cmd)
            os.system("ls -al build/outputs/apk/*.apk")

            ## cmd = "python ./scripts/flavors_generation.py" + " " + flavorName
            ## print ("Executing " + cmd)
            ## os.system(cmd)
            # cmd = "gradlew -PminSDK=21 -Propertyfile=" + flavorName + " " + buildCommand + flavorName + buildType
            cmd = "gradlew -Propertyfile=" + flavorName + buildOpt + buildCommand + flavorName + buildType
            print(("Executing " + cmd))
            code = os.system("stdbuf -o0 -e0 " + os.getcwd()+"/" + cmd)
            if code == 0:
                os.system("say -v karen 'Build successful'")
            else:
                os.system("say -v karen 'Build failed'")
    print ("[Done]")
