# Samtale

## Introducción
Este proyecto a consistido en el desarrollo en Python de un aplicación que permite el flujo de vídeo entre dos usuarios. Si bien Python es un gran aliado para este tipo de proyectos, como ya lo fue en el anterior, hemos encontrado más dificultades en el desarrollo de este. Procedemos a hacer una descripción de la estructura del proyecto, las decisiones de diseño más importantes y de las dificultades encontradas en el camino.

## Estructura del proyecto
El proyecto se divide en los siguientes archivos. Vamos a intentar hacer una descripción de menos complejo a más complejo.

### Decorators
En este fichero hemos implementado una serie de decoradores sumamente útiles. Destacan los siguientes:
* timeout: la función decorada con @timeout(milliseconds) se parará a los milliseconds milisegundos si no ha terminado. Aunque actualmente no lo usamos, inicialmente lo usábamos para cortar la lectura de la cámara si ésta era muy lenta (ahora con el modelo basado en Threads no es necesario).
* timer: esta función no la usamos tampoco en el código de develop/master pues es mayoritariamente para debuggear, ya que indica el tiempo en milisegundos que tarda una función en ejecutarse. La empleamos para estimar qué partes del código eran más lentas.
* run_in_thread: esta función la usamos extensamente para ejecutar funciones en un thread aparte y no bloquear el hilo principal.
* singleton: usado para implementar el patrón `Singleton`.

### User
Contiene las clases User y CurrentUser. La segunda hereda de la primera y añade una contraseña. Además, cabe destacar el método de User que calcula el protocolo común entre él y el CurrentUser, muy útil para determinar cual debe ser usado en una llamada. Además, la clase CurrentUser es un `Singleton`, pues la aplicación sólo puede ser usada por un usuario a la vez. Conseguimos implementar este patrón de diseño usando el decorador mencionado unas líneas más arriba. Por otro lado, contiene funciones para determinar la IP pública y privada del usuario.

### Discovery Server
Contiene todas las funciones relacionadas con el servidor de descubrimiento (para conseguir una lista de los usuarios conectados, los datos de un usuario en particular y para registrarse). Hemos tenido diversos problemas con la función LIST_USERS. En primer lugar, esta no devuelve los datos tal y como refleja la documentación, ya que en lugar de dar qué protocolos soporta un usuario, da el timestamp en el que se registró, información que no nos es útil. Sin embargo, esto lo solucionamos haciendo un QUERY de un usuario cuando vamos a llamarle para no solo tener su información actualizada (sus atributos pueden haber cambiado desde que llamamos a LIST_USERS), sino también para conocer qué protocolos soporta. Por otro lado, en ocasiones, esta función devuelve el contenido en respuestas separadas, por lo que es necesario llamar a recv varias veces. Además, no tenemos forma de saber cuando ha acabado de transmitir, ya que no acaba en ningún caracter especial. Como solución parcial, establecemos que este último carácter es '#', pero esto puede darse sin necesidad de que hayamos recibido la respuesta completa. Si en su lugar la respuesta acabase en un caracter especial, nuestro desarrollo permite una fácil adaptación.

### Configuration


### UDP Helper
Este módulo está dedicado a cubrir todo lo relacionado con los datagramas UDP que contienen el vídeo. Como debemos encapsular el datagrama UDP bajo una cabecera común, decidimos crear la clase `UDPDatagram`. De esta forma, tenemos tanto los datos como la cabecera integrados en un mismo objeto. Además, añadimos un método *encode* (similar al de la clase str) que permite codificar a bytes el datagrama. Esto es sumamente útil a la hora de enviarlo a través del socket.

Por otro lado, y mucho más importante, tenemos la clase `UDPBuffer`. Como su nombre indica, es el buffer que va a ir almacenando los paquetes de vídeo que van llegando. Tiene tres funciones bien diferenciadas:
* Permite la inserción ordenada de los frames que llegan por la red al buffer. Comienza intentando insertar por el final hasta que encuentra su posición. Al hacerlo, calcula la calidad estimada de la conexión basada en tres parámetros:
    * num_holes: es el número de huecos que tiene el buffer. Se le da mucha importancia al calcular el score pues no debería haber muchos huecos teniendo en cuenta que suele haber una media de BUFFER_MAX paquetes en el buffer.
    * packages_lost: histórico de paquetes perdidos. Como es una variable que refleja el número de paquetes perdidos en total, queremos darle una importancia relativa. Por ello, lo dividimos por el número de secuencia actual, que refleja el número de paquetes totales de la transmisión.
    * avg_delay: mide la media del delay. Si el delay es muy inestable o muy grande, es sinónimo de una conexión inestable. Por ello, siguiendo los valores recomendados por el libro de referencia de la asignatura, asignamos más o menos peso al score. Recordemos que estos valores hablan de que por debajo de 150 ms es excelente, entre 150 ms y 400 ms es aceptable, y más allá de esos 400 ms es inaceptable.
    
    Tras el cálculo del score, determinamos la calidad de la conexión como un valor de la enumeración `BufferQuality`. Básicamente, los número mágicos que aparecen son fruto de querer dar más importancia a unas variables que a otras y de muchas pruebas para ver que valores tenían mejor comportamiento.
    
    Cabe comentar un aspecto muy significativo en cuanto al delay. Sería una medida muy buena si los relojes de los dispositvos en la llamada van sincronizados. Sin embargo, tras realizar distintas pruebas, hemos comprobado que esto no es realmente así y los ts no se corresponden unos con otros. Esto provoca que, en ocasiones, la medida del delay no sea un valor real y pueda llevarnos a tomar decisiones erróneas. Por ejemplo, probando con un compañero que ejecutaba en Windows, nos salía un delay medio de 600 ms, cuando la conexión era perfecta y el vídeo no sufría ningún retraso. Es por ello que finalmente no realizamos control del delay al insertar, como sugirió el profesor. De hecho, fue al probar con este compañero cuando nos dimos cuenta del problema que suponía, ya que inicialmente habíamos incluido una restricción de un delay menor que 400 ms para poder ser insertado en el buffer, y en este caso no se insertaba nada aunque la comunicación fuese perfecta. La línea de código que comprobaba esa condición, y que por tanto descartaba paquetes con un delay superior a 400 ms a parte de por el número de secuencia, era la siguiente:
    
    ```python
    # If datagram should have already been consumed, discard it
    if datagram.seq_number < self.__last_seq_number or datagram.delay_ts >= UDPBuffer.MAXIMUM_DELAY:
        return False
    ```
* Permite la extracción de frames. Inicialmente no deja consumir hasta que el buffer se haya llenado parcialmente, para tener margen de maniobra a la hora de reproducir. Además, tampoco deja consumir más rápido que `time_between_frames` (media del tiempo entre paquetes estimado con los FPS), para evitar acelerar el vídeo. Sin embargo, si detecta que el buffer se está llenando en exceso, disminuye este tiempo para consumir ligeramente más rápido y evitar retrasos mayores. Al consumir, se recalcula el número de huecos que quedan en el buffer y el último número de secuencia consumido (usado para descartar paquetes anteriores a este número de secuencia).
* Avisa al hilo encargado de mostrar el vídeo por pantalla cada `time_between_frames` de que debe consumir. Daremos más detalles más adelante, pero este hilo encargado de mostrar vídeo también es avisado por el hilo que obtiene el vídeo "local" (ya se de la webcam o de un fichero).

### Call Control

### samtale.py


## Versión 1

## Conclusiones