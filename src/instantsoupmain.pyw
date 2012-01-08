#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
InstantSOUP
===========

The "Instant Satisfaction by Obscure Unstable Protocol" (InstantSOUP) is an application-level protocol for local message exchange.
The protocol was developed during a telematics project at Karlsruhe Institute of Technology (KIT) during the course of the winter semester 2011/2012.
InstantSOUP is responsible for connecting the user to a lobby in his or her local area network.
In this environment the user is able to interact with other participants and chat rooms.
"""

import sys
import logging

from PyQt4 import QtCore, QtGui, uic
from instantsoupdata import InstantSoupData, Client, Server
from thread import start_new_thread

# Initialize logger & set logging level
log = logging.getLogger("instantsoup")
log.setLevel(logging.DEBUG)
log.addHandler(logging.StreamHandler())

try:
    _fromUtf8 = QtCore.QString.fromUtf8
except AttributeError:
    _fromUtf8 = lambda s: s


class MainWindow(QtGui.QMainWindow):

    def __init__(self):
        super(MainWindow, self).__init__()

        self.init_server()
        self.init_client()
        self.init_ui()

    def init_server(self):
        self.server = Server(parent=self)

    def init_client(self):
        self.client = Client(parent=self)

    def init_ui(self):
        self.resize(800, 600)
        self.setWindowTitle('InstantSoup - Group 1')

        self.tab_widget = QtGui.QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setObjectName(_fromUtf8("tab_widget"))

        self.tab_lobby = uic.loadUi("gui/lobbyWidget.ui")
        self.tab_lobby.setObjectName(_fromUtf8("tab_lobby"))
        self.tab_widget.addTab(self.tab_lobby, _fromUtf8("Lobby"))

        grid_layout = QtGui.QGridLayout()
        grid_layout.setSizeConstraint(QtGui.QLayout.SetDefaultConstraint)
        grid_layout.setContentsMargins(9, -1, -1, -1)
        grid_layout.setHorizontalSpacing(6)
        grid_layout.setObjectName(_fromUtf8("grid_layout"))

        grid_layout.addWidget(self.tab_widget, 0, 0, 1, 1)

        central_widget = QtGui.QWidget()
        central_widget.setLayout(grid_layout)
        self.setCentralWidget(central_widget)

        # if we finish updating the nickname, process the new information
        self.tab_lobby.nicknameEdit.editingFinished.connect(self.update_nickname)

        self.tab_lobby.newChannelButton.clicked.connect(self.create_channel)

        self.client.new_server.connect(lambda : self.update_list())

    def update_nickname(self):

        # get the nickname from the gui field
        nickname = str(self.tab_lobby.nicknameEdit.text())

        # update the client and inform the server
        self.client.nickname = nickname
        self.client.send_client_nick()

    def create_channel(self):
        channel = str(self.tab_lobby.newChannelEdit.text())

        if channel == '':

            # user have to enter a name!
            msg_box = QtGui.QMessageBox()
            msg_box.setText('Please enter a channel name!')
            msg_box.exec_()
        else:
            self.client.join_channel(channel, self.server.id)

    def add_channel_to_tab(self, channel):
        tab_channel = uic.loadUi("gui/ChannelWidget.ui")
        tab_channel.setObjectName(_fromUtf8("tab_channel"))
#
        self.tab_widget.addTab(tab_channel, _fromUtf8(channel))

    def add_channel_to_list(self, channel):
        self.tab_lobby.channelsList.addItem(channel)

    def add_user_to_list(self, user):
        self.tab_lobby.usersList.addItem(user)

    def update_list(self):
        self.tab_lobby.channelsList.clear()

        for (key, value) in self.client.servers:
            if value != None:
                self.add_channel_to_list(value)


if __name__ == '__main__':
    app = QtGui.QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_())
