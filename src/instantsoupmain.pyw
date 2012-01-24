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
from PyQt4.QtCore import Qt, QString, QRegExp
from instantsoupdata import Client, Server
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

        #self.init_server()
        self.init_client()
        self.init_ui()

        # mapping from (server_id, channel_id) to (QWidget)
        self.tabs = {}

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
        self.lobby.nicknameEdit.editingFinished.connect(self._update_nickname)

        # if we want to create a channel, create it
        self.lobby.newChannelButton.clicked.connect(self._create_channel)

        # if we click on an item in the channel list
        self.lobby.channelsList.itemClicked.connect(self._handle_channel_list_click)

        # if we have a new client, show it
        self.client.client_new.connect(self._update_user_list)

        # if we have lost a client, show it
        self.client.client_removed.connect(self._update_user_list)

        # if we have an updated nickname, show it in user and channel list
        self.client.client_nick_change.connect(self._update_user_list)
        self.client.client_nick_change.connect(self._update_channel_list)

        # if we have a new membership, show it
        self.client.client_membership_changed.connect(self._update_channel_list)

        # if we have a new server, show it
        self.client.server_new.connect(self._update_channel_list)

        # if we have lost a server
        self.client.server_removed.connect(self._update_channel_list)

        # if we have a new message
        self.client.client_message_received[str, str].connect(self.output)

    def output(self, server_id, channel_id):
        key = (str(server_id), str(channel_id))
        if key in self.client.channel_history:
            if key in self.tabs:
                tab = self.tabs[key]

                tab.chatHistory.clear()
                tab.chatHistory.setOpenExternalLinks(True)

                for current_message in self.client.channel_history[key]:
                    (time, nickname, message) = current_message

                    # see   http://stackoverflow.com/questions/3321256/how-to
                    #       -use-regex-to-replace-urls-with-an-html-link-in-qt
                    qmessage = QtCore.QString(message)

                    # convert urls to hyperlinks
                    search = QRegExp("((?:https?|ftp)://\\S+)")
                    replace = QString("<a href=\"\\1\">\\1</a>")
                    qmessage.replace(search, replace)

                    line = ("<p><b>%s</b> <em>%s</em></p><p>%s</p>" % (nickname, time.toString(), qmessage))

                    tab.chatHistory.append(line)

    def get_invite_client_ids(self, tree_items):
        client_ids = set()
        for items in tree_items:
            try:
                client_ids.add(items.client_id)
            except AttributeError:
                pass
        try:
            client_ids.remove(self.client.id)
        except KeyError:
            pass
        return client_ids

    def get_invite_channel_id(self, tree_items):
        for item in tree_items:
            if hasattr(item, 'channel_id') and not hasattr(item, 'client_id'):
                if item.channel_id.startswith("@"):
                    return item.channel_id

    def _handle_channel_list_click(self, tree_item):
        tree_items = self.lobby.channelsList.selectedItems()

        # collect all client_ids for invite option
        client_ids = self.get_invite_client_ids(tree_items)
        invite_channel_id = self.get_invite_channel_id(tree_items)

        # do we have a channel_id?
        if hasattr(tree_item, 'channel_id'):

            items = set()
            iterator = QtGui.QTreeWidgetItemIterator(tree_item)
            iterator.__iadd__(1)

            # loop through all clients of a channel
            while iterator.value() != None:
                client_item = iterator.value()

                # do we have a client_id?
                if hasattr(client_item, 'client_id'):
                    items.add(client_item.client_id)
                iterator.__iadd__(1)

            # create the menu
            menu = QtGui.QMenu()
            action = QtGui.QAction(menu)

            # if we are not in channel -> enter, else -> leave
            if self.client.id not in items:
                action.setText("Enter Channel")
                action.triggered.connect(lambda:
                    self._enter_channel(tree_item))
            else:
                action.setText("Leave Channel")
                action.triggered.connect(lambda:
                    self._leave_channel(tree_item))
            menu.addAction(action)

            if client_ids and invite_channel_id:
                invite_action = QtGui.QAction(menu)
                invite_action.setText("Invite")
                invite_action.triggered.connect(lambda:
                    self.client.command_invite(client_ids,
                                               invite_channel_id,
                                               tree_item.server_id))
                menu.addAction(invite_action)

            # start menu
            menu.exec_(QtGui.QCursor.pos())

    def _update_nickname(self):

        # get the nickname from the gui field
        nickname = str(self.lobby.nicknameEdit.text())

        # update the client and inform the server
        self.client.nickname = nickname
        self.client.send_client_nick()

    def _create_channel(self):
        channel_id = str(self.lobby.newChannelEdit.text())

        # all selected items
        selected_items = self.lobby.channelsList.selectedItems()

        # if we have at least one selected item, go on
        if len(selected_items) > 0:
            server_id = selected_items[0].server_id

            # if we have a channel_id name, join it
            if channel_id:
                self.client.command_join(channel_id, server_id)
                tab = self._add_channel_to_tab(channel_id, server_id, channel_id)
                self.tabs[(server_id, channel_id)] = tab
            else:
                msg_box = QtGui.QMessageBox()
                msg_box.setText('Please enter a channel_id name!')
                msg_box.exec_()
        else:
            msg_box = QtGui.QMessageBox()
            msg_box.setText('Please select a server!')
            msg_box.exec_()

    def _enter_channel(self, tree_item):
        if hasattr(tree_item, 'channel_id'):
            server_id = tree_item.server_id
            channel_id = tree_item.channel_id
            channel_name = tree_item.text(0)

            # do some stuff :)
            self.client.command_join(channel_id, server_id)
            tab = self._add_channel_to_tab(channel_name, server_id, channel_id)
            self.tabs[(server_id, channel_id)] = tab

    def _leave_channel(self, tree_item):
        if hasattr(tree_item, 'channel_id'):
            server_id = tree_item.server_id
            channel_id = tree_item.channel_id

            # delete tab and exit
            self.client.command_exit(channel_id, server_id)
            tab = self.tabs[(server_id, channel_id)]
            self._remove_channel_from_tab(tab)
            del self.tabs[(server_id, channel_id)]

    def _remove_channel_from_tab(self, tab):
        number_of_tabs = len(self.tab_widget)
        i = 0
        while(i < number_of_tabs):
            if tab == self.tab_widget.widget(i):
                self.tab_widget.removeTab(i)
            i += 1

    def _add_channel_to_tab(self, channel_name, server_id, channel_id):
        tab_channel = uic.loadUi("gui/ChannelWidget.ui")
        tab_channel.setObjectName(_fromUtf8(channel_name))
        tab_channel.messageEdit.editingFinished.connect(lambda:
            self._send_message(tab_channel))
        tab_channel.chatHistory.setOpenExternalLinks(True)

        # a tab knows his server and channel
        tab_channel.server_id = server_id
        tab_channel.channel_id = channel_id

        self.tab_widget.addTab(tab_channel, _fromUtf8(channel_name))

        return tab_channel

    def _send_message(self, tab_channel):
        server_id = tab_channel.server_id
        channel_id = tab_channel.channel_id
        message = str(tab_channel.messageEdit.text())
        tab_channel.messageEdit.clear()

        self.client.command_say(message, channel_id, server_id)

    def _add_user_to_list(self, user):
        self.lobby.usersList.addItem(user)

    def _update_channel_list(self):
        self.lobby.channelsList.clear()
        server_channels = defaultdict(list)
        server_list = self.client.servers.items()

        for (server_id, channel_id), socket in server_list:
            key = (server_id, socket.peerAddress())
            server_channels[key].append((channel_id, socket))

        # show all servers in network
        for (server_id, address), channel_list in server_channels.items():

            # create root server and add to channels list
            root = QtGui.QTreeWidgetItem(["Server %s" %
                                          address.toString()])

            # set known identifiers
            root.server_id = server_id

            # add to root
            self.lobby.channelsList.addTopLevelItem(root)

            # show all channels of server
            for (channel_id, socket) in channel_list:
                if channel_id:
                    channel_text = (channel_id + ' (' +
                                    socket.localAddress().toString() + ':' +
                                    str(socket.localPort()) + ')')
                    channel = QtGui.QTreeWidgetItem([channel_text])

                    # set known identifiers
                    channel.server_id = server_id
                    channel.channel_id = channel_id

                    # add to root
                    root.addChild(channel)

                    # show all clients in channel
                    key = (server_id, channel_id)
                    if key in self.client.membership:
                        client_list = self.client.membership[key]
                        for client_id in client_list:
                            if client_id in self.client.users:
                                client_text = self.client.users[client_id]
                                client = QtGui.QTreeWidgetItem([client_text])

                                # set known identifiers
                                client.server_id = server_id
                                client.channel_id = channel_id
                                client.client_id = client_id

                                # add to root
                                channel.addChild(client)

        # show all
        self.lobby.channelsList.expandAll()

    def _update_user_list(self):
        self.lobby.usersList.clear()

        # create a list entry for every user
        for key in self.client.users:
            value = self.client.users[key]

            item = QtGui.QListWidgetItem()
            item.setText(value)

            self._add_user_to_list(item)

    def closeEvent(self, event):
        reply = QtGui.QMessageBox.question(self, 'Message',
            "Are you sure to quit?", QtGui.QMessageBox.Yes | 
            QtGui.QMessageBox.No, QtGui.QMessageBox.No)

        if reply == QtGui.QMessageBox.Yes:
            self.client.disconnect_from_all_channels()
            event.accept()
        else:
            event.ignore()

    def update_channel_user_list(self):
        tab = self.tab_widget.currentWidget()
        if tab != self.lobby:
            # namen reingecheatet
            tab.usersList = self.lobby.userLis

if __name__ == '__main__':
    app = QtGui.QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_())
