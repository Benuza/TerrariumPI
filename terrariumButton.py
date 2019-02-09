# -*- coding: utf-8 -*-
import terrariumLogging
logger = terrariumLogging.logging.getLogger(__name__)

import sys
try:
  import thread as _thread
except ImportError as ex:
  import _thread

# Dirty hack to include someone his code... to lazy to make it myself :)
# https://github.com/50ButtonsEach/fliclib-linux-hci
sys.path.insert(0, './fliclib-linux-hci/clientlib/python')
import fliclib

from hashlib import md5

from terrariumUtils import terrariumUtils, terrariumSingleton

from gevent import monkey, sleep
monkey.patch_all()

class terrariumButtonSource(object):
  TYPE = None
  TRIGGER_SINGLE = 'single'
  TRIGGER_DOUBLE = 'double'
  TRIGGER_HOLD   = 'hold'

  MAX_DELAY     = 5.0

  def __init__(self, button_id, address, name = '', trigger = TRIGGER_SINGLE, callback = None):
    self.button_id = button_id
    self.callback = callback

    self.set_address(address)
    self.set_name(name)
    self.set_trigger(trigger)

  def trigger_action(self,trigger):
    if self.get_trigger() == trigger:
      print('Trigger action: {}'.format(trigger))
      if self.callback is not None:
        print('Fire callback')
        # TODO: Fix proper logic ....
        self.callback(self.get_id())

  def get_id(self):
    if self.button_id in [None,'None','']:
      self.button_id = md5((self.get_type() + self.get_address() + self.get_trigger()).encode()).hexdigest()

    return self.button_id

  def get_type(self):
    return self.TYPE

  def set_address(self,address):
    self.address = address

  def get_address(self):
    return self.address

  def set_name(self,name):
    self.name = str(name)

  def get_name(self):
    return self.name

  def set_trigger(self,trigger):
    if trigger in [terrariumButtonSource.TRIGGER_SINGLE,terrariumButtonSource.TRIGGER_DOUBLE,terrariumButtonSource.TRIGGER_HOLD]:
      self.trigger = trigger

  def get_trigger(self):
    return self.trigger

class terrariumFlicButtonServer(terrariumSingleton):

  def __init__(self,host = 'localhost', port = 5551, button_list = None, callback = None):
    # This is a reference to the terrariumEmgine buttons list
    self.__button_list = button_list
    # This is the button callback to the terrariumEngine
    self.__call_back = callback

    # Create a tcp connection to the flic button daemon
    self.client = fliclib.FlicClient(host,port)
    # Load known buttons when connecting to the daemon
    self.client.get_info(self.__start_up)
    # When new buttons are added, add them to TerrariumPI also
    self.client.on_new_verified_button = self.__new_button
    # Start listening for button actions and changes
    _thread.start_new_thread(self.client.handle_events,())
    logger.info('Started the Flic bluetooth button daemon')

  def __start_up(self,items = None):
    # Loading existing known buttons
    for address in items["bd_addr_of_verified_buttons"]:
      self.__new_button(address)

  def __new_button(self,address):
    for button_trigger in terrariumFlicButton.TRIGGERS:
      button = terrariumButton(None,terrariumFlicButton.TYPE,address,'',button_trigger,self.__call_back)
      self.__button_list[button.get_id()] = button
      logger.info('Added new type {} button at address {} to the system with ID {} with trigger: {}.'.format(button.get_type(),
                                                                                                             button.get_address(),
                                                                                                             button.get_id(),
                                                                                                             button.get_trigger()))

class terrariumFlicButton(terrariumButtonSource):
  TYPE = 'flic'
  TRIGGERS = [terrariumButtonSource.TRIGGER_SINGLE,
              terrariumButtonSource.TRIGGER_DOUBLE,
              terrariumButtonSource.TRIGGER_HOLD]

  def __init__(self, button_id, address, name = '', action = terrariumButtonSource.TRIGGER_SINGLE, callback = None):
    super(terrariumFlicButton,self).__init__(button_id, address, name, action, callback)

    # This button server is a singleton, and should exists only once even when 10 buttons created
    self.__button_server = terrariumFlicButtonServer()

    button = fliclib.ButtonConnectionChannel(address)
    button.on_button_single_or_double_click_or_hold = \
      lambda channel, click_type, was_queued, time_diff: \
        self.__trigger_action(channel, click_type, was_queued, time_diff)

    self.__button_server.client.add_connection_channel(button)

  def __trigger_action(self, channel, click_type, was_queued, time_diff):
    if time_diff > terrariumButtonSource.MAX_DELAY:
      logger.warning('Button \'{}\' is slow in responding. Took {} seconds and is ignored due to more then {} seconds delay'.format(self.get_name(),
                                                                                                                                    time_diff,
                                                                                                                                    terrariumButtonSource.MAX_DELAY))
      return

    action = None
    if fliclib.ClickType.ButtonSingleClick == click_type:
      action = terrariumButtonSource.TRIGGER_SINGLE
    elif fliclib.ClickType.ButtonDoubleClick == click_type:
      action = terrariumButtonSource.TRIGGER_DOUBLE
    elif fliclib.ClickType.ButtonHold == click_type:
      action = terrariumButtonSource.TRIGGER_HOLD

    self.trigger_action(action)

  @staticmethod
  def scan_buttons(button_list,callback=None):
    try:
      terrariumFlicButtonServer(button_list=button_list,callback=callback)
    except Exception as ex:
      logger.warning('Exception scannig Flic buttons: {}'.format(ex))

class terrariumButtonTypeException(TypeError):
  '''There is a problem with loading a hardware switch. Invalid hardware type.'''

  def __init__(self, message, *args):
    self.message = message
    super(terrariumButtonTypeException, self).__init__(message, *args)

# Factory class
class terrariumButton(object):
  BUTTONS = []

  if sys.version_info >= (3, 3):
    # Flic SDK needs Python 3.3+
    BUTTONS.append(terrariumFlicButton)

  def __new__(self, button_id, hardware_type, address, name = '', trigger = terrariumButtonSource.TRIGGER_SINGLE, callback = None):
    for button in terrariumButton.BUTTONS:
      if hardware_type == button.TYPE:
        return button(button_id, address, name, trigger, callback)

    raise terrariumButtonTypeException('Button of type {} is unknown. We cannot controll this button.'.format(hardware_type))

  @staticmethod
  def valid_hardware_types():
    data = {}
    for button in terrariumButton.BUTTONS:
      data[button.TYPE] = button.TYPE

    return data

  @staticmethod
  def scan_buttons(button_list,callback=None):
    for button_device in terrariumButton.BUTTONS:
      try:
        button_device.scan_buttons(button_list, callback)
      except AttributeError as ex:
        logger.debug('Device \'{}\' does not support hardware scanning'.format(button_device.TYPE))

    # Add a sleep here, so that the callbacks can fire and update the button list
    sleep(1)
