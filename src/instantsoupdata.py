#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import uuid
import copy

from construct import Container, Enum, PrefixedArray, Struct, ULInt32
from construct import ULInt16, ULInt8, OptionalGreedyRange, PascalString
from construct import CString, Switch
from PyQt4 import QtCore, QtNetwork
from functools import partial
from collections import defaultdict

log = logging.getLogger("instantsoup")
log.setLevel(logging.DEBUG)

group_address = QtNetwork.QHostAddress("239.255.99.63")
broadcast_port = 55555
server_start_port = 49190


class InstantSoupData(object):

    # common
    server = Struct("server",
                 CString("server_id"),
                 PrefixedArray(CString('channels'),
                     ULInt8("num_channels")
                 )
             )

    # structures from rfc
    opt_client_nick = CString('nickname')

    opt_client_membership = PrefixedArray(server,
                                 ULInt8("num_servers")
                             )

    opt_server = Struct("opt_server",
                     ULInt16("port")
                 )

    opt_server_channels = Struct("opt_server_channels",
                             PrefixedArray(CString("channels"),
                                 ULInt8("num_channels"))
                          )

    opt_server_invite = Struct("opt_server_invite",
                             CString("channel_id"),
                             PrefixedArray(CString("client_id"),
                                 ULInt8("num_clients")
                             )
                         )

    # option fields
    option = Struct("option",
                 Enum(ULInt8("option_id"),
                     CLIENT_NICK_OPTION=0x01,
                     CLIENT_MEMBERSHIP_OPTION=0x02,
                     SERVER_OPTION=0x10,
                     SERVER_CHANNELS_OPTION=0x11,
                     SERVER_INVITE_OPTION=0x12
                 ),
                 Switch("option_data",
                     lambda ctx: ctx["option_id"],
                     {
                     "CLIENT_NICK_OPTION": opt_client_nick,
                     "CLIENT_MEMBERSHIP_OPTION": opt_client_membership,
                     "SERVER_OPTION": opt_server,
                     "SERVER_CHANNELS_OPTION": opt_server_channels,
                     "SERVER_INVITE_OPTION": opt_server_invite
                     }
                 )
             )

    # the peer pdu itself
    peer_pdu = Struct("peer_pdu",
                   CString('id'),
                   OptionalGreedyRange(option)
               )

    command = PascalString("command", length_field=ULInt32("length"))


class Client(QtCore.QObject):
    DEFAULT_WAITING_TIME = 1000

    REGULAR_PDU_WAITING_TIME = 15000

    DEFAULT_TIMEOUT_TIME = 2 * REGULAR_PDU_WAITING_TIME + DEFAULT_WAITING_TIME

    # emitted when a new client is discovered
    client_new = QtCore.pyqtSignal()

    # emitted when a new client is discovered
    client_removed = QtCore.pyqtSignal()

    # emitted when a nick of a client is changed
    client_nick_change = QtCore.pyqtSignal()

    # emitted when a other client joins or leaves a channel
    client_membership_changed = QtCore.pyqtSignal()

    # emitted when a new server is discovered
    server_new = QtCore.pyqtSignal()

    # emitted when a server is removed
    server_removed = QtCore.pyqtSignal()

    def __init__(self, nickname="Telematik", parent=None):
        QtCore.QObject.__init__(self, parent)

        self.id = str(uuid.uuid1())
        self.nickname = nickname
        self.pdu_number = 0

        self.create_udp_socket()

        # mapping from client.id to nickname
        self.users = {}

        # mapping from client.id to timer (which is a QTimer)
        self.users_timers = {}

        # mapping from (server_id, channel) to a tuple containing
        # (tcp_socket)
        self.servers = {}

        # mapping from (server_id, channel) to a tuple containing
        # (timer) - (which is a QTimer)
        self.servers_timers = {}

        # mapping from (server_id) to c(hannel_id) to a list of (client_ids)
        # stores the membership of this and OTHER peers
        self.membership = {}

        self.send_client_nick()

        # setup the regular_pdu_timer for the regular pdu
        self.regular_pdu_timer = QtCore.QTimer()
        self.regular_pdu_timer.timeout.connect(self.send_regular_pdu)
        self.regular_pdu_timer.start(self.REGULAR_PDU_WAITING_TIME)

    #
    # SOCKET FUNCTIONS
    #
    # create a socket for the PDUs
    def create_udp_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket()
        self.udp_socket.bind(broadcast_port,
                             QtNetwork.QUdpSocket.ReuseAddressHint)
        self.udp_socket.joinMulticastGroup(group_address)

        # connect the socket input with the processing function
        self.udp_socket.readyRead.connect(self.process_pending_datagrams)

    # create a socket for a channel
    def create_tcp_socket(self, address, port):
        socket = QtNetwork.QTcpSocket()

        # we have a port, connect!
        socket.connectToHost(address, port)

        if not socket.waitForConnected(self.DEFAULT_WAITING_TIME):
            raise Exception('no connection for address %s:%s' %
                      (address.toString(), port))

        # connect with processing function
        socket.readyRead.connect(partial(self.read_from_tcp_socket, socket))

        return socket

    def read_from_tcp_socket(self, tcp_socket):
        data = str(tcp_socket.readAll())
        tcp_socket.flush()
        self.handle_data(data, tcp_socket)
        tcp_socket.disconnected.connect(tcp_socket.deleteLater)

#
    # PROCESSING FUNCTIONS (INCOMING SERVER COMMANDOS)
    #
    def handle_data(self, command, tcp_socket):
        data = InstantSoupData.command.parse(command)

        if data.startswith("SAY"):
            print "SAY"
            #self.handle_say_command(data, tcp_socket)
        elif data.startswith("JOIN"):
            self.handle_join_command(data, tcp_socket)
        elif data.startswith("EXIT"):
            self.handle_exit_command(data, tcp_socket)

    #
    # SERVER COMMANDOS
    #
    def command_join(self, channel_id, server_id):
        key = (server_id, channel_id)

        socket = self.servers[(server_id, None)]
        address = socket.peerAddress()
        port = socket.peerPort()
        self.servers[key] = self.create_tcp_socket(address, port)

        # signal: we have a new server!
        self.server_new.emit()

        self.send_command_to_server("JOIN\x00%s" % channel_id,
                                    server_id, channel_id)

        # if combination not exist, create and be a member
        if key not in self.membership:
            self.membership[key] = set()
            self.membership[key].add(self.id)

        self.send_client_membership_option()

    def command_say(self, text, channel_id, server_id):
        self.send_command_to_server("SAY\x00%s" % text,
                                    server_id, channel_id)

    def command_standby(self, peer_id, channel_id, server_id):
        self.send_command_to_server("STANDBY\x00%s" % peer_id,
                                    server_id, channel_id)

    def command_exit(self, channel_id, server_id):
        self.send_command_to_server("EXIT", server_id, channel_id)

        # delete combination from memberships
        key = (server_id, channel_id)
        if key in self.membership:
            del self.membership[key]

        self.send_client_membership_option()

    def send_command_to_server(self, command, server_id, channel=None):
        if (server_id, channel) not in self.servers:
            log.error("server %s doesn't exist" % server_id)
        else:

            # we are already connected!
            socket = self.servers[(server_id, channel)]
            socket.write(InstantSoupData.command.build(command))
            socket.waitForBytesWritten(self.DEFAULT_WAITING_TIME)

    #
    # DATAGRAMS
    #
    def send_regular_pdu(self):

        # send nickname
        self.send_client_nick()

        # sent the option with every fourth pdu (see rfc)
        if self.pdu_number % 4 == 0:
            self.send_client_membership_option()

        self.pdu_number += 1

    def send_client_nick(self):

        # define the data to send & send
        option_data = self.nickname

        option = Container(option_id="CLIENT_NICK_OPTION",
                     option_data=option_data
                 )

        pdu = Container(id=self.id,
                  option=[option]
              )

        data = InstantSoupData.peer_pdu.build(pdu)
        self._send_datagram(data)

        log.debug('PDU: CLIENT_NICK_OPTION - ID: %i - SENT' % self.pdu_number)

    def send_client_membership_option(self):

        # mapping from server_id to a list of channel_ids
        server_channels = defaultdict(list)
        for (server_id, channel_id), _ in self.membership.items():
            if channel_id:
                server_channels[server_id].append(channel_id)

        # build the channel list for a server
        option_data = []
        for server_id, channels in server_channels.items():
            data = Container(server_id=server_id, channels=channels)
            option_data.append(data)

        # do we have something to send?
        if option_data:
            option = Container(option_id="CLIENT_MEMBERSHIP_OPTION",
                               option_data=option_data)
            pdu = Container(id=self.id, option=[option])
            data = InstantSoupData.peer_pdu.build(pdu)
            self._send_datagram(data)

        # SIGNAL: membership changed
        self.client_membership_changed.emit()
        log.debug('PDU: CLIENT_NICK_MEMBERSHIP - ID: %i - SENT' %
                  self.pdu_number)

    def _send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    #
    # PROCESSING FUNCTIONS (INCOMING PDUS)
    #
    def process_pending_datagrams(self):
        maxlen = self.udp_socket.pendingDatagramSize()
        while self.udp_socket.hasPendingDatagrams():
            (data, address, _) = self.udp_socket.readDatagram(maxlen)
            packet = InstantSoupData.peer_pdu.parse(data)
            peer_uid = packet["id"]
            for option in packet["option"]:

                if option["option_id"] == "CLIENT_NICK_OPTION":
                    self.handle_client_nick_option(peer_uid, option)
                elif option["option_id"] == "CLIENT_MEMBERSHIP_OPTION":
                    self.handle_client_membership_option(peer_uid, option)
                elif option["option_id"] == "SERVER_OPTION":
                    self.handle_server_option(peer_uid, option, address)
                elif option["option_id"] == "SERVER_CHANNELS_OPTION":
                    self.handle_server_channels_option(peer_uid, option)
                elif option["option_id"] == "SERVER_INVITE_OPTION":
                    self.handle_server_invite_option(peer_uid, option)

    def handle_client_nick_option(self, client_id, option):

        # new client found or client nick was changed
        if client_id in self.users:

            # user already exists
            if self.users[client_id] != option["option_data"]:
                self.users[client_id] = option["option_data"]

                # SIGNAL: client nick was changed
                self.client_nick_change.emit()
        else:

            # add new client
            self.users[client_id] = option["option_data"]
            self.users_timers[client_id] = QtCore.QTimer()
            self.users_timers[client_id].timeout.connect(lambda:
                                self.remove_client(client_id))

            # SIGNAL: new client
            self.client_new.emit()

        # restart the timer
        self.users_timers[client_id].start(self.DEFAULT_TIMEOUT_TIME)

    def handle_client_membership_option(self, client_id, option):
        servers = option["option_data"]
        for server_container in servers:
            server_id = server_container["server_id"]
            channels = server_container["channels"]
            for channel_id in channels:
                key = (server_id, channel_id)

                if key in self.membership:
                    self.membership[key].add(client_id)
                else:
                    self.membership[key] = set()
                    self.membership[key].add(client_id)

        # SIGNAL: memberships has changed
        self.client_membership_changed.emit()

    def handle_server_option(self, server_id, option, address):
        if (server_id, None) not in self.servers:

            # add new server
            port = option["option_data"]["port"]
            try:
                socket = self.create_tcp_socket(address, port)
                self.servers[(server_id, None)] = socket
                self.servers_timers[server_id] = QtCore.QTimer()
                self.servers_timers[server_id].timeout.connect(lambda:
                    self.remove_server(server_id))

                # SIGNAL: we have a new server!
                self.server_new.emit()
            except Exception as error:
                log.error(error)

        # restart the timer
        self.servers_timers[server_id].start(self.DEFAULT_TIMEOUT_TIME)

    def handle_server_channels_option(self, server_id, option):
        channels = option["option_data"]["channels"]
        for channel in channels:
            key = (server_id, channel)
            if key not in self.servers:
                try:
                    socket = self.servers[(server_id, None)]
                    address = socket.peerAddress()
                    port = socket.peerPort()
                    self.servers[key] = self.create_tcp_socket(address, port)

                    # signal: we have a new server!
                    self.server_new.emit()
                except Exception as error:
                    log.error(error)

    def handle_server_invite_option(self):
        pass

    def remove_server(self, key):
        self.servers_timers[key].stop()
        del self.servers_timers[key]

        # delete all server entries
        for (server_id, channel) in self.servers:
            if key == server_id:
                socket = self.servers[(server_id, channel)]
                socket.close()
                del self.servers[(server_id, channel)]

        # server removed
        self.server_removed.emit()

    def remove_client(self, key):
        self.users_timers[key].stop()
        del self.users_timers[key]
        del self.users[key]

        # client removed
        self.client_removed.emit()

    # Prints the Object
    def __repr__(self):
        return "Client(%s, %s, users:%s, servers:%s)" % (self.nickname,
            self.id,
            self.users,
            self.servers)


class Server(QtCore.QObject):
    DEFAULT_WAITING_TIME = 1000

    REGULAR_PDU_WAITING_TIME = 15000

    debug_output = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        global server_start_port

        QtCore.QObject.__init__(self, parent)

        # Create a channel with a unique id
        self.id = str(uuid.uuid1())
        self.port = server_start_port
        self.pdu_number = 0
        server_start_port += 1

        self.create_udp_socket()
        self.tcp_server = QtNetwork.QTcpServer(self)

        # mapping from (channel_id) to a list of (client_id, tcp_socket)
        self.channels = {}

        # mapping from (address) to (client_id)
        self.users = {}

        if not self.tcp_server.listen(QtNetwork.QHostAddress.Any, self.port):
            log.error("Unable to start the server: %s." %
                self.tcp_server.errorString())

        # Hint: IP: 0.0.0.0 means ANY
        address = self.tcp_server.serverAddress().toString()
        port = self.tcp_server.serverPort()
        log.debug("Server is running with address %s and port %s" % (address,
            port))

        # do something, when we are connected
        self.tcp_server.newConnection.connect(self.handle_connection)

        # setup the regular_pdu_timer for the regular pdu
        self.regular_pdu_timer = QtCore.QTimer()
        self.regular_pdu_timer.timeout.connect(self.send_regular_pdu)
        self.regular_pdu_timer.start(self.REGULAR_PDU_WAITING_TIME)

    #
    # SOCKET FUNCTIONS
    #
    # create a socket for the PDUs
    def create_udp_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket()
        self.udp_socket.bind(broadcast_port,
                             QtNetwork.QUdpSocket.ReuseAddressHint)
        self.udp_socket.joinMulticastGroup(group_address)

        # connect the socket input with the processing function
        self.udp_socket.readyRead.connect(self._process_pending_datagrams)

    def handle_connection(self):
        tcp_socket = self.tcp_server.nextPendingConnection()
        tcp_socket.disconnected.connect(tcp_socket.deleteLater)

        if not tcp_socket.waitForConnected(self.DEFAULT_WAITING_TIME):
            log.error((tcp_socket.error(),
               tcp_socket.errorString()))
            return

        # if the connection is ready, read from tcp_socket
        tcp_socket.readyRead.connect(partial(self.read_from_tcp_socket,
            tcp_socket))
        tcp_socket.waitForReadyRead(self.DEFAULT_WAITING_TIME)

    def read_from_tcp_socket(self, tcp_socket):
        data = str(tcp_socket.readAll())
        tcp_socket.flush()
        self.handle_data(data, tcp_socket)
        tcp_socket.disconnected.connect(tcp_socket.deleteLater)

    #
    # PROCESSING FUNCTIONS (INCOMING PDUS)
    #
    def _process_pending_datagrams(self):
        maxlen = self.udp_socket.pendingDatagramSize()

        # loop through all datagrams which are not send yet
        while self.udp_socket.hasPendingDatagrams():
            (datagram, address, _) = self.udp_socket.readDatagram(maxlen)
            packet = InstantSoupData.peer_pdu.parse(datagram)
            uid = packet['id']
            if uid != self.id:
                for option in packet["option"]:
                    if option["option_id"] == "CLIENT_NICK_OPTION":
                        self.handle_client_nick_option(address, uid)
                    elif option["option_id"] == "CLIENT_MEMBERSHIP_OPTION":
                        pass

    def handle_client_nick_option(self, address, client_id):
        self.users[address] = client_id

        # if we detect this option, maybe a new client was started
        # -> broadcast rapidly server data and channels
        self.send_server_option()
        timer = QtCore.QTimer()
        timer.singleShot(1000, self.send_server_channel_option)

    #
    # PROCESSING FUNCTIONS (INCOMING SERVER COMMANDOS)
    #
    def handle_data(self, command, tcp_socket):
        data = InstantSoupData.command.parse(command)

        if data.startswith("SAY"):
            self.handle_say_command(data, tcp_socket)
        elif data.startswith("JOIN"):
            self.handle_join_command(data, tcp_socket)
        elif data.startswith("EXIT"):
            self.handle_exit_command(data, tcp_socket)

    def handle_exit_command(self, data, tcp_socket):
        client_id = self.users[tcp_socket.peerAddress()]

        # remove client from channel
        for channel_id, client_sockets in self.channels.items():
            for (client_id, t_socket) in copy.copy(client_sockets):

                # compare sockets
                if (tcp_socket == t_socket):
                    self.channels[channel_id].remove((client_id, tcp_socket))

    def search_channel(self, tcp_socket):
        for channel_id, client_sockets in self.channels.items():
            for (client_id, t_socket) in client_sockets:

                # compare sockets
                if (tcp_socket == t_socket):
                    return client_id, channel_id

    def handle_say_command(self, data, tcp_socket):

        # send message to all connected peers in channel
        message = " ".join(data.split("\x00")[1:])

        try:
            author_id, channel_name = self.search_channel(tcp_socket)
            for (_, tcp_socket) in self.channels[channel_name]:
                command = "SAY\x00%s\x00%s\x00" % (author_id, message)
                data = InstantSoupData.command.build(command)
                tcp_socket.write(data)
                tcp_socket.waitForBytesWritten(self.DEFAULT_WAITING_TIME)
        except ValueError:
            log.error("tcp_socket was not found, make sure the tcp_socket is" +
                " associated with a channel. use the join command")

    def handle_join_command(self, data, tcp_socket):
        client_id = self.users[tcp_socket.peerAddress()]
        channel_name = data.split("\x00")[1]

        if channel_name in self.channels:
            self.channels[channel_name].add((client_id, tcp_socket))
        else:
            private = channel_name.startswith("@")

            # create a new channel
            self.channels[channel_name] = set()
            self.channels[channel_name].add((client_id, tcp_socket))

            if not private:
                self.send_server_channel_option()
            else:
                self.send_server_invite_option([client_id], channel_name)

    def send_server_invite_option(self, invite_client_ids, channel_id):

        # for each client_id find the socket on which to send the
        # server_invite option
        for invite_client_id in invite_client_ids:
            for channel_id, client_sockets in self.channels.items():
                for (client_id, socket) in client_sockets:
                    if invite_client_id == client_id:
                        option_data = Container(channel_id=channel_id,
                                          client_id=invite_client_ids
                                      )

                        option = Container(option_id="SERVER_INVITE_OPTION",
                                     option_data=option_data
                                 )

                        pdu = Container(id=self.id, option=[option])

                        socket.write(InstantSoupData.peer_pdu.build(pdu))
                        socket.waitForBytesWritten()
        log.debug('PDU: SERVER_INVITE_OPTION - id: %i - SENT' %
                  self.pdu_number)

    def send_regular_pdu(self):

        # simply send all data
        self.send_server_option()

        # sent the option with every fourth pdu (see rfc)
        if self.pdu_number % 4 == 0:
            self.send_server_channel_option()

    def send_server_option(self):

        # define the data to send & send
        option_data = Container(port=self.port)

        option = Container(option_id="SERVER_OPTION",
                   option_data=option_data)

        pdu = Container(id=self.id,
                option=[option])

        data = InstantSoupData.peer_pdu.build(pdu)
        self.send_datagram(data)

        log.debug('PDU: SERVER_OPTION - id: %i - SENT' % self.pdu_number)

        # increment the number of sent packets
        self.pdu_number += 1

    def send_server_channel_option(self):
        if self.channels:

            # define the data to send & send
            option_data = Container(channels=self.channels.keys())

            option = Container(option_id="SERVER_CHANNELS_OPTION",
                         option_data=option_data
                     )

            pdu = Container(id=self.id,
                    option=[option])

            data = InstantSoupData.peer_pdu.build(pdu)
            self.send_datagram(data)

            log.debug('PDU: SERVER_CHANNELS_OPTION - id: %i - SENT' %
                      self.pdu_number)

    def send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)
