/* ── Alpine.js: FullCalendar 日历组件 ── */
document.addEventListener('alpine:init', () => {
    Alpine.data('calendarApp', () => ({
        showModal: false,
        selectedEvent: {},
        calendar: null,

        init() {
            const calendarEl = document.getElementById('fc-calendar');
            if (!calendarEl) return;

            this.calendar = new FullCalendar.Calendar(calendarEl, {
                initialView: 'dayGridMonth',
                locale: 'zh-cn',
                height: 'auto',
                headerToolbar: {
                    left: 'prev,next today',
                    center: 'title',
                    right: 'dayGridMonth,timeGridWeek,timeGridDay'
                },
                buttonText: {
                    today: 'Today',
                    month: 'Month',
                    week: 'Week',
                    day: 'Day'
                },
                events: '/api/calendar/events',
                eventClick: (info) => {
                    info.jsEvent.preventDefault();
                    const props = info.event.extendedProps || {};
                    this.selectedEvent = {
                        id: info.event.id,
                        title: info.event.title,
                        start: info.event.start ? info.event.start.toLocaleString() : '',
                        end: info.event.end ? info.event.end.toLocaleString() : '',
                        description: props.description || '',
                        attendees: (props.attendees || []).join(', '),
                        location: props.location || '',
                        has_conflict: props.has_conflict || false,
                    };
                    this.showModal = true;
                },
                eventDidMount: (info) => {
                    if (info.event.extendedProps.has_conflict) {
                        info.el.style.borderLeft = '4px solid #e74c3c';
                    }
                }
            });
            this.calendar.render();
        },

        async deleteEvent() {
            if (!this.selectedEvent.id) return;
            try {
                const resp = await fetch(`/api/calendar/events/${this.selectedEvent.id}`, {
                    method: 'DELETE'
                });
                const data = await resp.json();
                showToast(data.message, resp.ok ? 'success' : 'error');
                if (resp.ok) {
                    this.calendar.refetchEvents();
                    this.showModal = false;
                }
            } catch (e) {
                showToast('Delete failed', 'error');
            }
        }
    }));
});
