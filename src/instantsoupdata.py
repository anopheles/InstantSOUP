#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import uuid
import copy

from construct import Container, Enum, PrefixedArray, Struct, ULInt32
from construct import ULInt16, ULInt8, OptionalGreedyRange, PascalString
from construct import CString, Switch, core
from PyQt4 import QtCore, QtNetwork
from collections import defaultdict
from time import gmtime, strftime

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

    command = PascalString("command", length_field=ULInt32("length"),
                           encoding='utf8')


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

    #emitted when a message was received from server
    client_message_received = QtCore.pyqtSignal(str, str)

    def __init__(self, nickname="Telematik", parent=None):
        QtCore.QObject.__init__(self, parent)

        self.id = str(uuid.uuid1())
        self.nickname = nickname
        self.pdu_number = 0

        self.create_udp_socket()

        # mapping from (client_id) to (nickname)
        self.users = {}

        # mapping from (client_id) to timer (which is a QTimer)
        self.users_timers = {}

        # mapping from (server_id, channel) to a tuple containing
        # (tcp_socket)
        self.servers = Lookup()

        # mapping from (server_id, channel) to a tuple containing
        # (timer) - (which is a QTimer)
        self.servers_timers = {}

        # mapping from (server_id, channel) to a list of tuple containing
        # (date, user, message)
        self.channel_history = {}

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

        # create the socket
        tcp_socket = QtNetwork.QTcpSocket(parent=self)

        # we have a destination port and address -> connect!
        tcp_socket.connectToHost(address, port)

        if not tcp_socket.waitForConnected(self.DEFAULT_WAITING_TIME):
            raise Exception('no connection for address %s:%s' %
                      (address.toString(), port))

        # connect with processing function
        tcp_socket.readyRead.connect(lambda:
            self.read_from_tcp_socket(tcp_socket))

        # if socket is disconnected, delete it later
        tcp_socket.disconnected.connect(tcp_socket.deleteLater)

        return tcp_socket

    def read_from_tcp_socket(self, tcp_socket):
        data = str(tcp_socket.readAll())
        tcp_socket.flush()
        self.handle_data(data, tcp_socket)

    #
    # PROCESSING FUNCTIONS (INCOMING SERVER COMMANDOS)
    #
    def handle_data(self, command, tcp_socket):
        try:
            data = InstantSoupData.command.parse(command)

            if data.startswith("SAY"):
                self.handle_say_command(data, tcp_socket)
        except core.FieldError:
            peer_pdu = InstantSoupData.peer_pdu.parse(command)
            # uid = peer_pdu["id"]
            for option in peer_pdu["option"]:
                if option["option_id"] == "SERVER_INVITE_OPTION":
                    log.debug("RECEIVED SERVER_INVITE_OPTION")
                    server_id = peer_pdu["id"]
                    channel_id = option["option_data"]["channel_id"]
                    client_ids = option["option_data"]["client_id"]
                    key = (server_id, channel_id)
                    # quick and dirty, probably not rfc conform
                    self.command_join(channel_id, server_id)
                    for client_id in client_ids:
                        if key in self.membership:
                            self.membership[key].add(client_id)
                        else:
                            self.membership[key] = set()
                            self.membership[key].add(client_id)

    def handle_say_command(self, data, tcp_socket):
        key = self.servers.find_key(tcp_socket)
        (server_id, channel_id) = key

        if channel_id is not None:

            client_id = data.split("\x00")[1]
            nickname = client_id

            # overwrite nickname if we have one
            if client_id in self.users:
                nickname = self.users[client_id]

            time = strftime("%Y-%m-%d %H:%M:%S", gmtime())
            message = QtCore.QString(" ".join(data.split("\x00")[2:]))

            if message.trimmed().length():
                entry = ("[%s] %s: %s" % (time, nickname, message))

                if key not in self.channel_history:
                    self.channel_history[key] = list()

                self.channel_history[key].append(entry)

                # SIGNAL: new message
                self.client_message_received.emit(server_id, channel_id)

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

    def command_invite(self, client_ids, channel_id, server_id):
        self.send_command_to_server("INVITE\x00%s" % "\x00".join(client_ids),
                                    server_id, channel_id)

    def command_exit(self, channel_id, server_id):
        self.send_command_to_server("EXIT", server_id, channel_id)

        # delete combination from memberships
        key = (server_id, channel_id)
        if key in self.membership:
            del self.membership[key]

        self.send_client_membership_option()

    def send_command_to_server(self, command, server_id, channel_id=None):
        key = (server_id, channel_id)
        if key not in self.servers:
            log.error("server %s doesn't exist" % server_id)
        else:

            # we are already connected!
            socket = self.servers[key]
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
            if channel_id and not channel_id.startswith("@"):
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

            # get the port
            port = option["option_data"]["port"]

            # create new socket
            socket = self.create_tcp_socket(address, port)

            # add the server itself to the server list
            self.servers[(server_id, None)] = socket

            # start timer for server timeout
            self.servers_timers[server_id] = QtCore.QTimer()
            self.servers_timers[server_id].timeout.connect(lambda:
                self.remove_server(server_id))

            # SIGNAL: we have a new server!
            self.server_new.emit()

        # restart the timer
        if server_id in self.servers_timers:
            self.servers_timers[server_id].start(self.DEFAULT_TIMEOUT_TIME)

    def handle_server_channels_option(self, server_id, option):
        channels = option["option_data"]["channels"]
        for channel in channels:
            key = (server_id, channel)
            if key not in self.servers:

                # get the socket of the server itself
                socket = self.servers[(server_id, None)]

                # get the server address and port
                address = socket.peerAddress()
                port = socket.peerPort()

                # create new socket (= tcp connection to server)
                self.servers[key] = self.create_tcp_socket(address, port)

                # SIGNAL: we have a new server!
                self.server_new.emit()

    def remove_server(self, key):
        self.servers_timers[key].stop()
        del self.servers_timers[key]

        # delete all server entries
        for (server_id, channel_id) in self.servers:
            if key == server_id:
                socket = self.servers[(server_id, channel_id)]
                del self.servers[(server_id, channel_id)]
                socket.close()

        # server removed
        self.server_removed.emit()

    def disconnect_from_all_channels(self):

        # get a independent list of the servers
        servers = copy.copy(self.servers)

        # delete all server entries
        for (server_id, channel_id) in servers:

            # we cannot exit the server itself!
            if channel_id is not None:
                self.command_exit(channel_id, server_id)

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

    DEFAULT_TIMEOUT_TIME = 2 * REGULAR_PDU_WAITING_TIME + DEFAULT_WAITING_TIME

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

        # mapping from (QHostAddress -> address) to (str -> client_id)
        self.users = {}

        # mapping from (QHostAddress -> address) to (QTimer -> timer)
        self.users_timers = {}

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

    def _get_channel_from_user_list(self, tcp_socket):
        for channel_id, client_sockets in self.channels.items():
            for (client_id, t_socket) in copy.copy(client_sockets):

                # compare sockets
                if tcp_socket == t_socket:
                    return channel_id, client_id

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

    # if server gets a new connection request create a socket
    def handle_connection(self):

        # next connection request
        tcp_socket = self.tcp_server.nextPendingConnection()

        # if socket is disconnected, delete it later
        tcp_socket.disconnected.connect(tcp_socket.deleteLater)

        if not tcp_socket.waitForConnected(self.DEFAULT_WAITING_TIME):

            # if there is no connection established, show error
            log.error((tcp_socket.error(), tcp_socket.errorString()))
        else:

            # if the connection is ready, read from tcp_socket
            tcp_socket.readyRead.connect(lambda:
                self.read_from_tcp_socket(tcp_socket))
            tcp_socket.waitForReadyRead(self.DEFAULT_WAITING_TIME)

    def read_from_tcp_socket(self, tcp_socket):
        data = str(tcp_socket.readAll())
        tcp_socket.flush()
        self.handle_data(data, tcp_socket)

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

    def handle_client_nick_option(self, address, client_id):
        do_update = False

        if address not in self.users:
            do_update = True
        else:
            if self.users[address] != client_id:
                do_update = True

        if do_update:
            self.users[address] = client_id

            # start timer for server timeout
            self.users_timers[address] = QtCore.QTimer()
            self.users_timers[address].timeout.connect(lambda:
                self.remove_client(address))

            # if we detect this option, maybe a new client was started
            # -> broadcast rapidly server data and channels
            self.send_server_option()
            timer = QtCore.QTimer()
            timer.singleShot(1000, self.send_server_channel_option)

        # restart the timer
        self.users_timers[address].start(self.DEFAULT_TIMEOUT_TIME)

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
        elif data.startswith("INVITE"):
            self.handle_invite_command(data, tcp_socket)

    def handle_exit_command(self, data, tcp_socket):
        address = tcp_socket.peerAddress()

        # is user known?
        if address in self.users:
            client_id = self.users[tcp_socket.peerAddress()]
            channel_id, _ = self._get_channel_from_user_list(tcp_socket)

            # is channel known?
            if channel_id in self.channels:
                key = (client_id, tcp_socket)

                # remove if set
                if key in self.channels[channel_id]:
                    self.channels[channel_id].remove(key)

    def handle_say_command(self, data, tcp_socket):
        address = tcp_socket.peerAddress()

        # is user known?
        if address in self.users:

            # build the key to get the channel_id
            client_id = self.users[address]
            channel_id, _ = self._get_channel_from_user_list(tcp_socket)
            message = " ".join(data.split("\x00")[1:])

            # is channel known?
            if channel_id in self.channels:

                # send to all clients in channel
                for (_, socket) in self.channels[channel_id]:
                    command = "SAY\x00%s\x00%s\x00" % (client_id, message)
                    data = InstantSoupData.command.build(command)
                    socket.write(data)
                    socket.waitForBytesWritten(self.DEFAULT_WAITING_TIME)

    def handle_join_command(self, data, tcp_socket):
        address = tcp_socket.peerAddress()

        # is user known?
        if address in self.users:
            client_id = self.users[address]
            channel_name = data.split("\x00")[1]

            # is channel known?
            if channel_name in self.channels:
                self.channels[channel_name].add((client_id, tcp_socket))
            else:
                private = channel_name.startswith("@")

                # create a new channel
                self.channels[channel_name] = set()
                self.channels[channel_name].add((client_id, tcp_socket))

                if not private:
                    self.send_server_channel_option()

    def handle_invite_command(self, data, tcp_socket):
        #client_id = self.users[tcp_socket.peerAddress()]
        channel_id, _ = self._get_channel_from_user_list(tcp_socket)
        invite_client_ids = data.split("\x00")[1:]
        self.send_server_invite_option(invite_client_ids, channel_id)
        #print client_id, "wants to invite", invite_client_ids, "into channel", channel_id
        #print "raw data", repr(data)

    def send_server_invite_option(self, invite_client_ids, channel_id):
        # for each client_id find the socket on which to send the
        # server_invite option
        for invite_client_id in invite_client_ids:
            for _, client_sockets in self.channels.items():
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
        public_channels = [channel for channel in self.channels if not channel.startswith("@")]
        if public_channels:

            # define the data to send & send
            option_data = Container(channels=public_channels)

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

    def remove_client(self, key):
        self.users_timers[key].stop()
        del self.users_timers[key]
        del self.users[key]

# search a dictionary for key or value
# using named functions or a class
# tested with Python25   by Ene Uran    01/19/2008


class Lookup(dict):
    """
    a dictionary which can lookup value by key, or keys by value
    """

    def __init__(self, items=[]):
        """items can be a list of pair_lists or a dictionary"""
        dict.__init__(self, items)

    def get_key(self, value):
        """find the key(s) as a list given a value"""
        return [item[0] for item in self.items() if item[1] == value]

    def get_value(self, key):
        """find the value given a key"""
        return self[key]

    def find_key(self, val):
        """return the key of dictionary dic given the value"""
        return [k for k, v in self.iteritems() if v == val][0]

    def find_value(self, key):
        """return the value of dictionary dic given the key"""
        return self[key]
