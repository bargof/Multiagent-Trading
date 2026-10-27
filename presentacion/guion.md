# Guion de la presentación

Unos 8 minutos. Entre corchetes, lo que muestro en pantalla.

---

## Apertura · 20 s

Hice un comité de inversión con cinco agentes de IA: leen noticias y
reportes, analizan una compra sobre un portafolio y la pasan por una revisión
de riesgo. Pero lo que quiero mostrar no es si el agente acierta, sino cómo
lo evalué.

---

## El tipo de sistema y el diagrama · 2.5 min

[Diagrama]

Primero, qué tipo de sistema multiagente es, porque de eso depende todo lo
demás. Usé un **supervisor con agentes como herramientas, dentro de un grafo
de control determinista**.

Antes de programar comparé cuatro patrones:

- **Supervisor:** un agente central decide a quién consultar. Lo elegí como
  base, porque centraliza la delegación y solo activa a los especialistas que
  hacen falta.
- **Grafo de control:** lo puse alrededor del supervisor, para imponer los
  pasos que no pueden quedar a criterio de un modelo, como revisar el riesgo y
  validar.
- **Paralelo:** podría servir para consultas independientes, pero en esta
  versión no lo usé. Todo corre de uno en uno, para que la traza sea clara.
- **Enjambre**, donde los agentes se pasan el control entre ellos: lo
  descarté. Ese traspaso libre agrega variación y ciclos que en un comité de
  inversión no quiero.

Por eso las flechas del diagrama son tareas y respuestas, no traspasos de
control. El supervisor nunca le entrega el caso a otro agente: le pide algo,
recibe el resultado y sigue decidiendo él.

La idea que lo resume es: **los modelos deciden e interpretan, pero el código
calcula y controla.**

[Señalar la caja punteada]

Arriba está el grafo. El camino de cada solicitud está fijado en código:
iniciar, supervisor, clasificar la salida y, si hay propuesta, revisión de
riesgo y validación. Ningún modelo puede saltarse un paso.

[Señalar A0, A1, A2 y A3]

El supervisor, A0, recibe la pregunta y decide qué necesita. No consulta
datos ni hace cálculos: llama a los especialistas como si fueran
herramientas. A1 lee noticias, A2 analiza el reporte financiero y A3 trabaja
con el portafolio. Cada uno solo puede usar sus propias herramientas, y cada
vez que lo llaman empieza sin memoria, así que no arrastra nada de otra
consulta.

[Señalar revisar_riesgo y verificar_control]

Si A0 propone una compra, el grafo siempre la manda a A4, el de riesgo. Eso
no lo decide A0: está en el código. Después viene la validación
determinista, que recalcula los límites de la política. Ahí ninguna
aprobación, ni la del usuario ni la de un modelo, puede saltarse un límite.
Si A4 encuentra un problema, puede devolver el caso al supervisor, como
máximo dos veces.

[Señalar la Mesa y los datos]

Todas las llamadas a herramientas pasan por la Mesa, que revisa permisos,
lleva el presupuesto de cada caso y guarda la traza que después evalúo. Los
datos son ficticios y viven dentro del archivo, para que la evaluación no
dependa del mercado del día.

[Señalar el recuadro verde]

Y a la derecha está el control humano. Si la propuesta cumple, el sistema no
la ejecuta: queda pendiente para que una persona decida. Si no cumple, se
bloquea. No existe ninguna herramienta para ejecutar operaciones.

---

## Cómo lo evalué · 2 min

[Tabla de rutas del informe]

La evaluación la definí **antes de programar el sistema**: en el documento
de plan quedó una evaluación a priori. Cada caso tiene sus cinco campos: la
entrada tal como la escribe el usuario, la trayectoria esperada con sus
argumentos, el resultado esperado con su tolerancia, y cómo se compara cada
uno. Esos valores no salen de lo que respondió el sistema: los calculé a
mano a partir de los datos ficticios.

Después los copié al código como una clave de respuestas, separada de los
agentes. Ningún agente la ve: ni en su prompt ni en sus herramientas.

Son cinco casos, uno por cada tipo que pide la rúbrica:

- **R1:** explicar una noticia.
- **R2:** cruzar una noticia con el reporte financiero, con dos agentes.
- **R3:** un cálculo que hice a mano antes.
- **R4:** pedir un precio con la fuente caída a propósito.
- **R5:** una compra que rompe el límite, con el usuario diciendo «yo lo
  autorizo».

Y uno extra, R6: una compra válida que debe quedar esperando a una persona.

En cada caso comparo por separado el camino y la respuesta.

En el camino reviso qué agentes y herramientas usó, con qué argumentos y en
qué orden. El criterio depende del caso: en R1 exige coincidencia exacta,
porque una sola herramienta basta y cualquier paso extra sobra. En R2 acepta
cualquier orden, porque noticias y finanzas son independientes. En los demás
exige orden, porque hay datos que dependen de otros: primero el precio,
después el cálculo.

En la respuesta, las cifras se comparan con tolerancia de un centavo y los
estados tienen que ser exactos. En R1 y R2, que son texto libre, uso un juez
LLM con tres criterios escritos de antemano.

Antes de probar el sistema probé el evaluador: le di 23 trazas con errores
plantados y comprobé que los detectara todos. Después congelé el archivo y
corrí cada caso tres veces. Reporto la peor ejecución, no la mejor.

---

## Decisiones en el camino · 1 min

Tomé y documenté 58 decisiones. Las más importantes:

- **Los modelos.** Usé la capa gratuita de Gemini. La primera campaña se
  cortó porque el modelo que elegí solo permite 20 llamadas al día y
  necesitaba unas 150. No la borré: la reporto. Cambié a modelos más chicos
  que permiten 500, y el juez es un modelo distinto al de los agentes.
- **Si el proveedor falla**, esa corrida se guarda, no cuenta y se repite.
  Pero si ya había hecho algo prohibido, cuenta como falla. Lo decidí antes
  de correr, para no poder escoger resultados.
- **La temperatura.** La dejé sin fijar, porque la guía de Gemini 3 lo
  recomienda. Por eso hay variación entre repeticiones.

---

## Resultados · 1 min

[Resumen del informe]

- **9 de 15 aprobadas.**
- R1 y R2, perfectas: 3 de 3.
- R3, R4 y R5: 1 de 3 cada una. R6: 2 de 3.
- Lo más importante: **R5 bloqueó la compra las tres veces**, aunque el
  usuario insistía, y en las 18 corridas no hubo ninguna acción prohibida.

---

## Qué significa · 1 min

[Análisis de fallas]

**Los controles nunca fallaron**, porque no dependen del modelo: están en
código.

**Las fallas fueron de coordinación, no de cálculo.** Ninguna cifra salió
mal, porque las calculan las herramientas. Lo que falló fue el modelo
organizándose: el supervisor pasó la cantidad en el texto y no como dato en
3 de 6 propuestas, una vez cambió el orden de dos pasos, y otra trató un
cálculo como si fuera una compra.

**El evaluador también se equivocó**, y eso me parece lo más interesante.
En R4 el agente hizo todo bien, pero citó una fecha con su zona horaria,
«menos 06», y el evaluador leyó ese 06 como una cifra inventada. Lo confirmé
en mi revisión: sin esos dos falsos positivos serían 11 de 15. Aun así dejo
el resultado oficial en 9, porque no reescribo lo que dijo el evaluador.

**Y el juez:** revisé sus 18 criterios y coincidí en 17. En el que no, fue
más generoso que yo.

---

## Qué seguiría · 30 s

Corregir el detector de cifras y correr otra campaña. Hacer obligatoria la
cantidad en la delegación, que fue la falla más repetida. Y probar con un
modelo más grande, para separar lo que es del diseño de lo que es del tamaño
del modelo.

---

## Cierre · 10 s

En resumen: 9 de 15, cero fallas de control, y cada error explicado paso por
paso. Todo sale de un solo archivo que cualquiera puede correr. Gracias.

---

## Si me preguntan

**¿Por qué no 15 de 15?** La rúbrica califica la evaluación, no que el agente
acierte. Prefiero reportar lo que pasó.

**¿Cambiaste algún esperado?** No. Las expectativas tienen una huella
congelada, y la campaña comprueba que no cambiaron. Ni siquiera corregí el
falso positivo de R4.

**¿Por qué modelos chicos?** Por la cuota: 20 llamadas al día contra 500.

**¿Confías en el juez?** Solo para texto libre, nunca para números, y lo
contrasté con mi revisión.

**¿Qué pasa si el usuario insiste?** Es R5. Aunque el agente de riesgo le
hiciera caso, la validación en código bloquea la compra. Pasó las tres veces.
