# Perfil do mkimage do Alpine: "JukeOS"
profile_slotos() {
	profile_standard
	profile_abbrev="slotos"
	title="JukeOS"
	desc="Liga e abre direto o Play Musica Jukebox Karaoke"
	arch="x86_64"
	kernel_flavors="lts"
	kernel_cmdline="console=tty1 quiet loglevel=3"
	hostname="slotos"
	apkovl="genapkovl-slotos.sh"
	apks="alpine-base alpine-baselayout busybox openrc
		eudev udev-init-scripts udev-init-scripts-openrc libinput
		seatd cage chromium
		mesa-dri-gallium mesa-egl mesa-gles mesa-gbm
		font-dejavu alsa-utils alsa-lib alsa-ucm-conf alsa-plugins-pulse
		pulseaudio pulseaudio-alsa pulseaudio-utils sof-firmware
		python3 ntfs-3g
		linux-firmware-i915 linux-firmware-amdgpu linux-firmware-radeon"
	local _k
	for _k in $kernel_flavors; do
		apks="$apks linux-$_k"
	done
}
