# The net package
## Overview
The net package contains three major components:
1. A simple experiment message protocol defining standard signals for communicating experiment events
2. A Communicator base class that implements method that send these signals and register/trigger callback events
3. A Services class for sending and awaiting messages from multiple Communicators

## Echo protocol
The Communicator is implemented as net.app.EchoProtocol which can be instantiated in either a 'client' or 'server' role.
A 'server' is a single main acquisition PC which listens on a specified local port and sends messages to multiple remote clients.
A 'client' is one of potentially many auxiliary acquisition PCs that await commands from the same remote server.

NB: The role you instantiate represents the role of the _remote computer_ that you are connecting to.

### Example
**On an auxiliary acquisition PC (client computer)**
```python
from iblutil.io import net
lan_ip = net.base.hostname2ip()  # Local area network IP of this PC
server_uri = net.base.validate_uri(lan_ip, default_port=9998)  # Listen for server message on this local port
server = await net.app.EchoProtocol.server(server_uri, name='server')
```

**On the main acquisition PC (server computer)**
```python
from iblutil.io import net
server_uri = net.base.validate_uri('192.168.1.256', default_port=9998)  # Remote server hostname and port
client = await net.app.EchoProtocol.client(server_uri, name='aux_PC')
```

Typically the server sends one of a number of signals to each client computer, such as 'EXPINIT', 'EXPSTART', 'EXPSTOP'.
The full set of supported signals are found in the `net.base.ExpMessage` enumeration.  All messages sent are a JSON array
where the first element is expected to be the signal enumeration, e.g. `b'[20, "2022-01-01_1_subject", {"foo": "bar"}]'` 
for an EXPSTART signal.

Every message sent is expected to be immediately echoed back as confirmation of receipt at the API level.  
If an echo isn't received in time a TimeoutError is raised.  The default echo timeout is set by the `net.app.EchoProtocol.default_echo_timeout` attribute.

Convenience methods are available for sending these messages, e.g. `net.app.EchoProtocol.init()`.  
These are async functions that return (None) when the echo is received:

```python
# Send EXPSTART signal to auxillary PC with an experiment reference and some arbitrary data
await client.start('2022-01-01_1_subject', data={'foo': 'bar'})  # b'[20, "2022-01-01_1_subject", {"foo": "bar"}]'
```

### Event callbacks
For listening to events (typically on the auxillary PC) you can either register a synchronous callback function or await
the event.  When an event is received, the callback(s) are called with the data and the remote address as a (hostname, port)
tuple.

**Register a basic callback (synchronous)**
```python
# Register a callback that prints the data to system out
event = net.base.ExpMessage.EXPSTART
server.assign_callback(event, lambda data, addr: print(data))
```

**Awaiting events (asynchronous)**
```python
event = net.base.ExpMessage.EXPINIT
data, addr = await server.on_event(event)

...  # Some initialization routine

# Let remote server know we're initialized as a service (optional)
await server.init(addr=addr)
```

## Services
A Services object can be used for managing multiple auxiliary PCs at once.  This provides convenience methods for sending
the same message to all clients, sequentially or concurrently, and optionally waiting for all their responses.

This is a small extension to the echo protocol where in addition to immediately echoing the message as confirmation of receipt,
the remote client also sends the same signal with optional extra data to indicate that it has finished processing the signal.

**Create a Services object on the main acquisition PC**
```python
clients = {
    'client 1': 'udp://192.168.1.256',
    'client 2': 'udp://192.168.0.330',
    'client 3': 'udp://192.168.0.1'
}
remote_rigs = [await net.app.EchoProtocol.client(uri, name) for name, uri in clients.items()]
services = net.app.Services(remote_rigs)

# Assign a callback to all clients
callback = lambda _, addr: print('{}:{} finished clean up'.format(*addr))
services.assign_callback('EXPCLEANUP', callback)

# Remove this callback
services.clear_callbacks('EXPCLEANUP', callback)

# Assign callback that receives client instance
callback = lambda *_, rig: print(f'{rig.name} finished clean up')
services.assign_callback('EXPCLEANUP', callback, return_service=True)
```

The `init` and `start` methods send an EXPINIT and EXPSTART message to each client in the order the were provided to the
constructor.  The `cleanup` and `stop` methods send their messages to the clients in reverse order.  The methods return a
dictionary of rig names and their responses.

**Sequential service**
```
Server                                                      Client
===================================================================
[client 1].start ------------- EXPSTART -------------->   [client 1]._receive
(awaiting confirmation)                                        |
[client 1] <------------------ EXPSTART ---------------   [client 1].send (echo)
    |                                                          |
(awaiting update)                                          (starting)
    |                                                          |
[client 1].on_event <--------- EXPSTART ---------------   [client 1].send (update)
    |
[client 2].start ------------- EXPSTART -------------->   [client 2]._receive
(awaiting confirmation)                                        |
[client 2] <------------------ EXPSTART ---------------   [client 2].send (echo)
    |                                                          |
(awaiting update)                                          (starting)
    |                                                          |
[client 2].on_event <--------- EXPSTART ---------------   [client 2].send (update)
  [...]
[client n].start ------------- EXPSTART -------------->   [client n]._receive
(awaiting confirmation)                                        |
[client n] <------------------ EXPSTART ---------------   [client n].send (echo)
    |                                                          |
(awaiting update)                                          (starting)
    |                                                          |
[client n].on_event <--------- EXPSTART ---------------   [client n].send (update)
```
```python
responses = await services.start('2022-01-01_1_subject', concurrent=False)
```

**Concurrent services**
```
Server                                                      Client
===================================================================
[client 1].start ------------- EXPSTART -------------->   [client 1]._receive
(awaiting confirmation)                                        |
[client 1] <------------------ EXPSTART ---------------   [client 1].send (echo)
    |                                                          ┴
[client 2].start ------------- EXPSTART -------------->   [client 2]._receive
(awaiting confirmation)                                        |
[client 2] <------------------ EXPSTART ---------------   [client 2].send (echo)
    |                                                          ┴
  [...]
    |
[client n].start ------------- EXPSTART -------------->   [client n]._receive
(awaiting confirmation)                                        |
[client n] <------------------ EXPSTART ---------------   [client n].send (echo)
    |                                                          ┴
(awaiting updates)
    |
[client 2] <------------------ EXPSTART ---------------   [client 2].send (update)
[client 1] <------------------ EXPSTART ---------------   [client 1].send (update)
  [...]
[client n] <------------------ EXPSTART ---------------   [client n].send (update)
```
```python
responses = await services.init(concurrent=True)
```

## See Also
[Functions for Alyx callbacks and creating services from experiment description file.](https://github.com/int-brain-lab/iblscripts/blob/udps/deploy/behaviourpc/remote_devices.py)
