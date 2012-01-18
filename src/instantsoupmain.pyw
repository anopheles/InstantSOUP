#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
InstantSOUP
===========

The "Instant Satisfaction by Obscure Unstable Protocol" (InstantSOUP) is an
application-level protocol for local message exchange. The protocol was
developed during a telematics project at Karlsruhe Institute of Technology
(KIT) during the course of the winter semester 2011/2012. InstantSOUP is
responsible for connecting the user to a lobby in his or her local area
network. In this environment the user is able to interact with other
participants and chat rooms.
"""

import sys
import logging
import time

from PyQt4 import QtCore, QtGui, uic
from instantsoupdata import InstantSoupData, Client, Server
from thread import start_new_thread
from functools import partial
from collections import defaultdict

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
        self.tab_channel_list = list()

    def init_server(self):
        self.server = Server(parent=self)

    def init_client(self):
        self.client = Client(parent=self)

    def init_ui(self):
        self.resize(800, 600)
        self.setWindowTitle('InstantSoup - Group 1')

        self.tab_widget = QtGui.QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(False)
        self.tab_widget.setObjectName(_fromUtf8("tab_widget"))

        self.lobby = uic.loadUi("gui/lobbyWidget.ui")
        self.lobby.setObjectName(_fromUtf8("lobby"))
        self.tab_widget.addTab(self.lobby, _fromUtf8("Lobby"))

        grid_layout = QtGui.QGridLayout()
        grid_layout.setSizeConstraint(QtGui.QLayout.SetDefaultConstraint)
        grid_layout.setContentsMargins(9, -1, -1, -1)
        grid_layout.setHorizontalSpacing(6)
        grid_layout.setObjectName(_fromUtf8("grid_layout"))

        grid_layout.addWidget(self.tab_widget, 0, 0, 1, 1)

        central_widget = QtGui.QWidget()
        central_widget.setLayout(grid_layout)
        self.setCentralWidget(central_widget)

        # --- Qt Signal & Slots connections ---

        # if we finish updating the nickname, process the new information
        self.lobby.nicknameEdit.editingFinished.connect(self.update_nickname)

        # if we want to create a channel, create it
        self.lobby.newChannelButton.clicked.connect(self.create_channel)

        # if we press enter in the input field, create the channel
        self.lobby.newChannelEdit.editingFinished.connect(self.create_channel)

        # if we want to enter a channel, enter
        self.lobby.channelsList.itemDoubleClicked.connect(self.enter_channel)

        # if we have a new server, show it
        self.client.server_new.connect(self.update_channel_list)

        # if we have a new client, show it
        self.client.client_new.connect(self.update_user_list)

        # if we have an updated nickname, show it
        self.client.client_nick_change.connect(self.update_user_list)

        # if we have a new membership, show it
        self.client.client_membership_changed.connect(self.update_channel_list)

        # if we have lost a server
        self.client.server_removed.connect(self.update_channel_list)

        # if we click on an item in the channel list
        self.lobby.channelsList.itemClicked.connect(self._handle_channel_list_click)

    def _handle_channel_list_click(self, tree_item):
        if hasattr(tree_item, "client_id"):
            client_item = tree_item
            if client_item.client_id == self.client.id:
                menu = QtGui.QMenu()
                leave_action = QtGui.QAction("Leave Channel", menu)
                leave_action.triggered.connect(lambda : self.client.command_exit(client_item.channel_id, client_item.uid))
                menu.addAction(leave_action)
                menu.exec_(QtGui.QCursor.pos())
            else:
                print "clicked on different client"



    def update_nickname(self):

        # get the nickname from the gui field
        nickname = str(self.lobby.nicknameEdit.text())

        # update the client and inform the server
        self.client.nickname = nickname
        self.client.send_client_nick()

    def create_channel(self):
        channel = str(self.lobby.newChannelEdit.text())

        # try to get the server id from the channels list
        try:
            server_id = self.lobby.channelsList.selectedItems()[0].uid
        except IndexError:
            server_id = self.server.id

        # user has to enter a name for the channel!
        if not channel:
            msg_box = QtGui.QMessageBox()
            msg_box.setText('Please enter a channel name!')
            msg_box.exec_()
        else:
            self.client.command_join(channel, server_id)

    def enter_channel(self, tree_item):
        if tree_item.is_channel:
            channel_item = tree_item        
            self.tab_channel_list.append(channel_item.uid)
            self.add_channel_to_tab(channel_item.text(0))
            
    def add_channel_to_tab(self, channelname):
        tab_channel = uic.loadUi("gui/ChannelWidget.ui")
        tab_channel.setObjectName(_fromUtf8("tab_channel"))
        tab_channel.messageEdit.editingFinished.connect(self.send_message)
        #self.client.server_sends_message.connect(self.display_message)
        self.tab_widget.addTab(tab_channel, _fromUtf8(channelname))
            
    def send_message(self):
        index = self.tab_widget.currentIndex()-1
        server_id = self.tab_channel_list[index]
        server_name = self.tab_widget.tabText(0)
        message = str(self.tab_widget.currentWidget().messageEdit.text())
        self.tab_widget.currentWidget().messageEdit.clear()
        self.client.command_say(message, server_name, server_id)
    
    def display_message(self, nickname, text, server_id):
        try:
            list_position = self.tab_channel_list.index(server_id)
            textbox = self.tab_widget.widget(list_position+1).chatHistory
            textbox.insertPlainText(self.to_chat_format(nickname, text))
            textbox.insertPlainText("\n")
            
        except IndexError:
            print "Can not display the message"
            
    def to_chat_format(self, nickname, text):
        text = time.strftime("%d.%m.%Y %H:%M:%S")+" "+nickname+" :"+text       
        return text
               
    def add_user_to_list(self, user):
        self.lobby.usersList.addItem(user)

    def update_channel_list(self):
        self.lobby.channelsList.clear()
        server_channels = defaultdict(list)
        server_list = self.client.servers.items()

        for (se_id, ch_id), (address, port, _) in server_list:
            server_channels[(se_id, address)].append((ch_id, port))

        # show all servers in network
        for (se_id, address), channel_list in server_channels.items():

            # create root server and add to channels list
            root = QtGui.QTreeWidgetItem(["Server %s" % address.toString()])
            root.uid = se_id
            root.is_channel = False
            self.lobby.channelsList.addTopLevelItem(root)

            # show all channels of server
            for (ch_id, port) in channel_list:
                if ch_id:
                    channel_text = ch_id + ' (' + address.toString() + ':' + str(port) + ')'
                    channel = QtGui.QTreeWidgetItem([channel_text])
                    channel.uid = se_id
                    channel.is_channel = True
                    root.addChild(channel)

                    # show all clients in channel
                    client_list = self.client.channel_membership[se_id][ch_id]
                    for cl_id in client_list:
                        client_text = self.client.lobby_users[cl_id]
                        client = QtGui.QTreeWidgetItem([client_text])
                        client.uid = se_id
                        client.client_id = cl_id
                        client.is_channel = False
                        client.channel_id = ch_id
                        channel.addChild(client)

        # show all
        self.lobby.channelsList.expandAll()

    def update_user_list(self):
        self.lobby.usersList.clear()

        # create a list entry for every user
        for key in self.client.lobby_users:
            value = self.client.lobby_users[key]

            item = QtGui.QListWidgetItem()
            item.setText(value)

            self.add_user_to_list(item)
        
    def update_channel_user_list(self):
        tab = self.tab_widget.currentWidget()
        if tab != self.lobby:
            # namen reingecheatet
            tab.usersList = self.lobby.userList
            
            
if __name__ == '__main__':
    app = QtGui.QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_())
