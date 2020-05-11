# Samtale

## Installation
Using a virtual environment is highly recommended. To do so:
- Install `virtualenv` if you do not have it already by running:
  ```bash
  sudo pip3 install virtualenv
  ```
- Create a virtual environment in the desired location and with the desired name (venv in the example):
  ```bash
  virtualenv venv
  ```
  To specify Python3 as the interpreter (required for this project), create the environment running:
  ```bash
  virtualenv --python=python3 venv
  ```
- Activate your virtual environment:
  ```bash
  source venv/bin/activate
  ```
- Deactivate it if wanted:
  ```bash
  deactivate
  ```

## Requirements
Python3 is required to run this project. Moreover, all the required libraries are indicated in `requirements.txt`. It is recommended to install them in the virtual environment. To do so, after activating it, just run:
```bash
pip install -r requirements.txt
```

## Usage
The GUI has the following widgets:
* Search bar: the user may here look for other users nicknames so as to call them.
* Connect: when the desired user is selected with the search bar, pressing Connect button starts a call with him. This button changes its message according to the call state.
* Register: if the current user is not registered, he can do so by clicking on this button. By clicking on it, the App asks the user to fill the required information. Apart from writing the nick and those details, he can specify if he wants to be remembered (a configuration.ini file will be stored for the next time) and if he wants to be registered using his private IP (in case he wants to use the App in LAN). If he is already registered, his nickname will be displayed in this button instead. By clicking on it, the App will show his data and offer the opportunity to log out, which means that the App will be closed and his configuration file deleted (if the user just wants to close the App, he can click the X button).
* End Call: button used to terminate a call. It does nothing when the user is not in a call.
* Hold/Resume: button used to hold the call or resume it, depending on the previous state of the call. Note that the call will only flow if both users agree. This means that if one user press Hold and the other does the same just after him, both users will have to press Resume if they want the call to flow again.
* Select video: if the user wants to broadcast a video, this is the button to be clicked. After clicking on it, the App will ask the user to select the video to be sent. After this is done, the button changes to Clear video. This button should be clicked when the user wants to use the WebCam again.

Apart from these widgets, dialog messages will be displayed to inform the user of what is happening: if he wants to Accept or Deny a call, if the other user accepted/denied/ended the call, ...

## Execution
Just run the following and enjoy!
```bash
python samtale.py
```