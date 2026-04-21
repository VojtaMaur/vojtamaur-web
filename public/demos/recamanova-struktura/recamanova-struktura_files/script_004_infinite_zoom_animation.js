const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');

function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
}

resizeCanvas();

class Turtle {
    constructor(x, y) {
        this.x = x;
        this.y = y;
        this.angle = 0; 
        this.isPenDown = true;
    }

    forward(distance) {
        const newX = this.x + distance * Math.cos(this.angle);
        const newY = this.y + distance * Math.sin(this.angle);

        if (this.isPenDown) {
            ctx.beginPath();
            ctx.moveTo(this.x, this.y);
            ctx.lineTo(newX, newY);
            ctx.stroke();
        }

        this.x = newX;
        this.y = newY;
    }

    left(angle) {
        this.angle -= this.degToRad(angle);
    }

    right(angle) {
        this.angle += this.degToRad(angle);
    }

    degToRad(deg) {
        return (deg * Math.PI) / 180;
    }
}

function generateRecamanSequence(n) {
    const recaman = [0];
    for (let i = 1; i < n; i++) {
        const nextValue = recaman[i - 1] - i;
        if (nextValue > 0 && !recaman.includes(nextValue)) {
            recaman.push(nextValue);
        } else {
            recaman.push(recaman[i - 1] + i);
        }
    }
    return recaman;
}

let offsetX = 0;
let offsetY = 0;
let zoom = 1;
const zoomFactor = 1.3;

canvas.addEventListener('mousemove', function(event) {
    if (event.buttons == 1) {
        offsetX += event.movementX;
        offsetY += event.movementY;
        drawTurtleGraphics();
    }
});

canvas.addEventListener('wheel', function(event) {
    const rect = canvas.getBoundingClientRect();
    const mouseX = event.clientX - rect.left;
    const mouseY = event.clientY - rect.top;

    // Aktuální pozice kurzoru na plátně před zoomem (uvažujeme offset a zoom)
    const xBeforeZoom = (mouseX - offsetX) / zoom;
    const yBeforeZoom = (mouseY - offsetY) / zoom;

    // Upravíme hodnotu zoom
    if (event.deltaY < 0) {
        zoom *= zoomFactor;
    } else {
        zoom /= zoomFactor;
    }

    // Očekávaná pozice kurzoru na plátně po zoomu
    const xAfterZoom = xBeforeZoom * zoom;
    const yAfterZoom = yBeforeZoom * zoom;

    // Upravíme offset tak, aby skutečná pozice na plátně byla stejná jako očekávaná
    offsetX = mouseX - xAfterZoom;
    offsetY = mouseY - yAfterZoom;

    drawTurtleGraphics();
    event.preventDefault();
});


let currentStep = 0;

function drawTurtleGraphics() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const turtle = new Turtle((canvas.width / 2) * zoom + offsetX, (canvas.height / 2) * zoom + offsetY);
    const recamanSequence = generateRecamanSequence(20000);
    const scale = 8;

    for (let i = 0; i < currentStep && i < recamanSequence.length; i++) {
        const angle = recamanSequence[i];
        turtle.left(angle);
        turtle.forward(scale * zoom);
    }

    currentStep++;

    if (currentStep <= recamanSequence.length) {
        setTimeout(drawTurtleGraphics, 10);
    } else {
        currentStep = 0; // Reset the current step to start the animation again
        setTimeout(drawTurtleGraphics, 10);
    }
	
}




drawTurtleGraphics();
